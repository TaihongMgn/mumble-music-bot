# coding=utf-8
"""Ximalaya.com item - downloads the m4a before playing."""
import base64
import hashlib
import logging
import os
import struct
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

log = logging.getLogger("bot")

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/150.0.0.0 Safari/537.36',
}


def _rc4(cipher_text, key):
    """RC4 decryption (from yt-dlp videa extractor, MIT license)."""
    res = b''
    key_len = len(key)
    S = list(range(256))
    j = 0
    for i in range(256):
        j = (j + S[i] + ord(key[i % key_len])) % 256
        S[i], S[j] = S[j], S[i]
    i = 0
    j = 0
    for m in range(len(cipher_text)):
        i = (i + 1) % 256
        j = (j + S[i]) % 256
        S[i], S[j] = S[j], S[i]
        k = S[(S[i] + S[j]) % 256]
        res += struct.pack('B', k ^ cipher_text[m])
    return res.decode()


def decrypt_url_params(encrypted):
    """Decrypt ep param -> (sign, token, timestamp)."""
    params = _rc4(
        base64.b64decode(encrypted), 'xkt3a41psizxrh9l').split('-')
    return params[1], params[2], params[3]


def decrypt_filename(file_id, seed):
    """Decrypt fileId into the real file path (from yt-dlp, MIT license)."""
    cgstr = ''
    key = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ/\\:._-1234567890'
    for _ in key:
        seed = float(int(211 * seed + 30031) % 65536)
        r = int(seed / 65536 * len(key))
        cgstr += key[r]
        key = key.replace(key[r], '')
    parts = file_id.split('*')
    filename = ''.join(cgstr[int(part)] for part in parts if part.isdecimal())
    if not filename.startswith('/'):
        filename = '/' + filename
    return filename


def _xm_load_cookie():
    """读取喜马拉雅 cookie（与 interface.py 一致）。"""
    if os.path.isdir('/config'):
        path = '/config/ximalaya_cookie.txt'
    else:
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'config/ximalaya_cookie.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except (IOError, FileNotFoundError):
        return ''


def _fetch_vip_url(track_id, cookie):
    """通过 mpay 接口获取会员音频 URL。

    实测（2026-08-21）：mpay 接口**匿名**请求返回 ret=0 + isAuthorized=true
    的完整版音频；带登录 cookie 反而触发风控（ret=999 账号异常）。
    因此这里不携带 Cookie 头。
    """
    import time
    ts = int(time.time())
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/150.0.0.0 Safari/537.36',
    }
    resp = requests.get(
        'https://mpay.ximalaya.com/mobile/track/pay/{}/{}'.format(track_id, ts),
        params={'device': 'pc', 'isBackend': 'true', '_': ts},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    vip_info = resp.json()
    if vip_info.get('ret') != 0 or not vip_info.get('fileId'):
        return None
    filename = decrypt_filename(vip_info['fileId'], vip_info['seed'])
    sign, token, timestamp = decrypt_url_params(vip_info['ep'])
    buy_key = vip_info.get('buyKey', '')
    url = ("{domain}/download/{apiVersion}{filename}"
           "?sign={sign}&token={token}&timestamp={timestamp}"
           "&duration={duration}").format(
        domain=vip_info['domain'],
        apiVersion=vip_info['apiVersion'],
        filename=filename,
        sign=sign,
        token=token,
        timestamp=timestamp,
        duration=vip_info['duration'],
    )
    if buy_key:
        url += '&buy_key=' + buy_key
    return url


def ximalaya_item_builder(**kwargs):
    return XimalayaItem(
        kwargs['track_id'],
        kwargs.get('title', ''),
        kwargs.get('artist', ''),
    )


def ximalaya_item_loader(_dict):
    return XimalayaItem("", from_dict=_dict)


def ximalaya_item_id_generator(**kwargs):
    return hashlib.md5(
        ("ximalaya:" + str(kwargs['track_id'])).encode()
    ).hexdigest()


item_builders['ximalaya'] = ximalaya_item_builder
item_loaders['ximalaya'] = ximalaya_item_loader
item_id_generators['ximalaya'] = ximalaya_item_id_generator


class XimalayaItem(BaseItem):
    def __init__(self, track_id, title="", artist="", from_dict=None):
        self.validating_lock = threading.Lock()
        if from_dict is None:
            super().__init__()
            self.track_id = str(track_id)
            self.title = title or ''
            self.artist = artist or ''
            self.url = ''
            self.duration = 0
            self.is_paid = False
            self.id = ximalaya_item_id_generator(track_id=self.track_id)
            self.path = os.path.join(var.tmp_folder, self.id + ".m4a")
            self.keywords = "{} {}".format(self.title, self.artist).strip()
        else:
            super().__init__(from_dict)
            self.track_id = str(from_dict.get('track_id', ''))
            self.artist = from_dict.get('artist', '') or ''
            self.url = from_dict.get('url', '') or ''
            self.is_paid = bool(from_dict.get('is_paid', False))
            self.path = from_dict.get('path') or os.path.join(
                var.tmp_folder, self.id + ".m4a")

        # interface.playlist() expects every media item to expose thumbnail.
        self.thumbnail = ''
        self.downloading = False
        self.type = "ximalaya"

    def uri(self):
        return self.path

    def is_ready(self):
        if self.downloading or self.ready != 'yes':
            return False
        if not os.path.exists(self.path):
            self.log.info(
                "ximalaya: music file missed for %s",
                self.format_debug_string())
            self.ready = 'validated'
            return False
        return True

    def _fetch_detail(self):
        resp = requests.get(
            'https://m.ximalaya.com/tracks/{}.json'.format(self.track_id),
            headers=UA,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

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
                detail = self._fetch_detail()
                if detail.get('is_paid'):
                    self.is_paid = True
                    # mpay 接口匿名即可获取完整版（带 cookie 反而触发风控），
                    # 直接尝试；失败才提示需登录会员。
                    try:
                        vip_url = _fetch_vip_url(self.track_id, '')
                        if vip_url:
                            self.url = vip_url
                            self.title = detail.get('title', '') or self.title
                            self.artist = detail.get('nickname', '') or self.artist
                            self.duration = int(float(detail.get('duration', 0) or 0))
                            self.thumbnail = detail.get('cover_url', '') or ''
                            self.keywords = "{} {}".format(self.title, self.artist).strip()
                            self.ready = 'validated'
                            self.version += 1
                            return True
                    except (requests.RequestException, ValueError, TypeError, KeyError):
                        log.exception("ximalaya: VIP URL fetch failed for %s", self.track_id)
                    # 解密失败
                    self.ready = 'failed'
                    raise ValidationFailedError(tr('ximalaya_paid_prompt'))

                url = detail.get('play_path_64') or detail.get('play_path_32')
                if not url:
                    self.ready = 'failed'
                    raise ValidationFailedError(tr('ximalaya_play_error'))

                self.url = url
                self.title = detail.get('title', '') or self.title
                self.artist = detail.get('nickname', '') or self.artist
                try:
                    self.duration = int(float(detail.get('duration', 0) or 0))
                except (TypeError, ValueError):
                    self.duration = 0
                self.keywords = "{} {}".format(
                    self.title, self.artist).strip()
                try:
                    self.thumbnail = detail.get('cover_url', '') or ''
                except AttributeError:
                    self.thumbnail = ''
            except ValidationFailedError:
                raise
            except (requests.RequestException, ValueError, TypeError):
                self.ready = 'failed'
                self.log.exception(
                    "ximalaya: could not validate track %s", self.track_id)
                raise ValidationFailedError(tr('ximalaya_play_error'))

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
        self.downloading = True
        self.ready = 'preparing'
        partial_path = self.path + '.part'
        response = None

        try:
            with util.tmp_folder_quota(
                    var.tmp_folder,
                    var.config.getint('bot', 'tmp_folder_max_size'),
                    protected_paths=(self.path, partial_path)) as quota:
                self.log.info(
                    "ximalaya: downloading %s - %s", self.title, self.artist)
                try:
                    response = requests.get(
                        self.url,
                        stream=True,
                        timeout=30,
                        headers=UA,
                    )
                    response.raise_for_status()
                except requests.RequestException:
                    # Direct URLs expire after about 20 minutes, so revalidate once.
                    self.log.warning(
                        "ximalaya: download URL failed for %s, re-validating",
                        self.track_id)
                    if response is not None:
                        response.close()
                        response = None
                    self.url = ''
                    try:
                        self.validate()
                    except ValidationFailedError:
                        raise
                    if not self.url:
                        raise
                    response = requests.get(
                        self.url,
                        stream=True,
                        timeout=30,
                        headers=UA,
                    )
                    response.raise_for_status()

                content_length = response.headers.get('content-length')
                try:
                    content_length = int(content_length) if content_length else 0
                except (TypeError, ValueError):
                    content_length = 0
                if content_length:
                    quota.ensure_capacity(content_length)

                with open(partial_path, 'wb') as file:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            # Check before each write so an unknown or incorrect
                            # Content-Length cannot grow the directory unboundedly.
                            quota.ensure_capacity(len(chunk))
                            file.write(chunk)

                os.replace(partial_path, self.path)
                quota.ensure_capacity()
                self.ready = 'yes'
                self.version += 1  # notify wrapper to save the 'yes' state
                self.log.info("ximalaya: finished downloading %s", self.path)
        except (requests.RequestException, OSError, util.TmpFolderLimitError) as error:
            self.log.error("ximalaya: download failed: %s", error)
            self.ready = 'failed'
            try:
                os.remove(partial_path)
            except FileNotFoundError:
                pass
            except OSError:
                self.log.warning(
                    "ximalaya: could not remove partial file %s", partial_path)
            raise PreparationFailedError(
                tr('unable_download', item=self.format_title()))
        finally:
            if response is not None:
                response.close()
            self.downloading = False

        return True

    def format_title(self):
        return self.title or "Ximalaya {}".format(self.track_id)

    def format_song_string(self, user):
        return tr(
            'ximalaya_song_item',
            title=self.title or self.format_title(),
            artist=self.artist,
            user=user,
        )

    def format_current_playing(self, user):
        return tr('now_playing', item=self.format_song_string(user))

    def display_type(self):
        return tr('ximalaya')

    def to_dict(self):
        dict_data = super().to_dict()
        dict_data['track_id'] = self.track_id
        dict_data['artist'] = self.artist
        dict_data['is_paid'] = self.is_paid
        return dict_data
