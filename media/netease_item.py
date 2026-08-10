# coding=utf-8
"""Netease Cloud Music item - downloads the song before playing."""
import hashlib
import logging
import os
import threading

import requests

import util
import variables as var
from constants import tr_cli as tr
from media.item import (
    BaseItem,
    PreparationFailedError,
    ValidationFailedError,
    item_builders,
    item_id_generators,
    item_loaders,
)
from netease import NeteaseClient, NeteaseCookieManager


log = logging.getLogger("bot")


def netease_item_builder(**kwargs):
    return NeteaseItem(
        kwargs['song_id'],
        kwargs.get('title', ''),
        kwargs.get('artist', ''),
    )


def netease_item_loader(_dict):
    return NeteaseItem("", from_dict=_dict)


def netease_item_id_generator(**kwargs):
    return hashlib.md5(
        ("netease:" + str(kwargs['song_id'])).encode()
    ).hexdigest()


item_builders['netease'] = netease_item_builder
item_loaders['netease'] = netease_item_loader
item_id_generators['netease'] = netease_item_id_generator


class NeteaseItem(BaseItem):
    def __init__(self, song_id, title="", artist="", from_dict=None):
        self.validating_lock = threading.Lock()
        if from_dict is None:
            super().__init__()
            self.song_id = str(song_id)
            self.title = title or ''
            self.artist = artist or ''
            self.url = ''
            self.duration = 0
            self.id = netease_item_id_generator(song_id=self.song_id)
            self.path = os.path.join(var.tmp_folder, self.id + ".mp3")
            self.keywords = "{} {}".format(self.title, self.artist).strip()
        else:
            super().__init__(from_dict)
            self.song_id = str(from_dict.get('song_id', ''))
            self.artist = from_dict.get('artist', '') or ''
            self.url = from_dict.get('url', '') or ''
            self.path = from_dict.get('path') or os.path.join(
                var.tmp_folder, self.id + ".mp3")

        # interface.playlist() expects every media item to expose thumbnail.
        self.thumbnail = ''
        self.downloading = False
        self.type = "netease"

    @staticmethod
    def _duration_seconds(value):
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            return 0
        # Netease API returns milliseconds; media items use seconds.
        if value > 1000:
            value /= 1000
        return int(round(value))

    def uri(self):
        return self.path

    def is_ready(self):
        if self.downloading or self.ready != 'yes':
            return False
        if not os.path.exists(self.path):
            self.log.info(
                "netease: music file missed for %s", self.format_debug_string())
            self.ready = 'validated'
            return False
        return True

    def _get_client_and_cookie(self):
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        cookie_manager = NeteaseCookieManager(
            var.config.get(
                'netease', 'cookie_file', fallback='config/netease_cookie.txt'))
        return client, cookie_manager.get_cookie()

    def validate(self):
        with self.validating_lock:
            # A complete local file is the cache hit; no API request is needed.
            if os.path.exists(self.path):
                if self.ready != 'yes':
                    self.ready = 'yes'
                    self.version += 1  # notify wrapper to save the 'yes' state
                return True

            if self.ready in ['yes', 'validated']:
                # previously validated but the file is gone -> re-fetch URL
                self.ready = 'validated'

            try:
                client, cookie = self._get_client_and_cookie()
                url = client.get_song_url(self.song_id, cookie)
                if not url:
                    self.ready = 'failed'
                    raise ValidationFailedError(tr('netease_play_error'))

                self.url = url
                if not self.title or not self.artist or not self.duration:
                    detail = client.get_song_detail(self.song_id)
                    if detail:
                        self.title = detail.get('name', '') or self.title
                        self.artist = detail.get('artist', '') or self.artist
                        self.duration = self._duration_seconds(
                            detail.get('duration', 0)) or self.duration
                        self.keywords = "{} {}".format(
                            self.title, self.artist).strip()
            except ValidationFailedError:
                raise
            except (requests.RequestException, ValueError, TypeError):
                self.ready = 'failed'
                self.log.exception(
                    "netease: could not validate song %s", self.song_id)
                raise ValidationFailedError(tr('netease_play_error'))

            max_duration = var.config.getint('bot', 'max_track_duration') * 60
            if max_duration and self.duration and self.duration > max_duration:
                raise ValidationFailedError(
                    tr('too_long',
                       song=self.format_title(),
                       duration=util.format_time(self.duration),
                       max_duration=util.format_time(max_duration)))

            self.ready = 'validated'
            self.version += 1
            return True

    # Run in another thread.
    def prepare(self):
        if not self.downloading:
            assert self.ready == 'validated'
            return self._download()
        assert self.ready == 'yes'
        return True

    def _download(self):
        util.clear_tmp_folder(
            var.tmp_folder,
            var.config.getint('bot', 'tmp_folder_max_size'))
        self.downloading = True
        self.ready = 'preparing'
        partial_path = self.path + '.part'

        try:
            self.log.info(
                "netease: downloading %s - %s", self.title, self.artist)
            response = requests.get(
                self.url,
                stream=True,
                timeout=30,
                headers={'User-Agent': 'Mozilla/5.0'},
            )
            response.raise_for_status()
            with open(partial_path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file.write(chunk)
            response.close()
            os.replace(partial_path, self.path)
            self.ready = 'yes'
            self.version += 1  # notify wrapper to save the 'yes' state
            self.log.info("netease: finished downloading %s", self.path)
        except (requests.RequestException, OSError) as error:
            self.log.error("netease: download failed: %s", error)
            self.ready = 'failed'
            try:
                os.remove(partial_path)
            except FileNotFoundError:
                pass
            except OSError:
                self.log.warning(
                    "netease: could not remove partial file %s", partial_path)
            raise PreparationFailedError(
                tr('unable_download', item=self.format_title()))
        finally:
            self.downloading = False

        return True

    def format_title(self):
        return self.title or "Netease {}".format(self.song_id)

    def format_song_string(self, user):
        return tr(
            'netease_song_item',
            title=self.title or self.format_title(),
            artist=self.artist,
            user=user,
        )

    def format_current_playing(self, user):
        return tr('now_playing', item=self.format_song_string(user))

    def display_type(self):
        return tr('netease')

    def to_dict(self):
        dict_data = super().to_dict()
        dict_data['song_id'] = self.song_id
        dict_data['artist'] = self.artist
        dict_data['url'] = self.url
        return dict_data
