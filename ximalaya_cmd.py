# coding=utf-8
"""Mumble commands for Ximalaya (喜马拉雅)."""
import logging
import math
import re

import requests

from constants import tr_cli as tr
from media.cache import get_cached_wrapper_from_scrap
import variables as var


log = logging.getLogger("bot")

__all__ = [
    "cmd_xm_dispatch",
    "cmd_xm_play",
    "cmd_xm_add",
]

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/150.0.0.0 Safari/537.36',
}

_SOUND_RE = re.compile(
    r'ximalaya\.com/(?:\d+/)?sound/(\d+)', re.IGNORECASE)
_ALBUM_RE = re.compile(
    r'ximalaya\.com/(?:\d+/)?album/(\d+)', re.IGNORECASE)
_NUMBER_RE = re.compile(r'^\d+$')


def _send(bot, text, key, **kwargs):
    bot.send_msg(tr(key, **kwargs), text)


def _queue_track(bot, user, track_id, title="", artist=""):
    music_wrapper = get_cached_wrapper_from_scrap(
        type="ximalaya",
        track_id=track_id,
        title=title,
        artist=artist,
        user=user,
    )
    var.playlist.append(music_wrapper)
    log.info(
        "cmd: add Ximalaya item to playlist: %s",
        music_wrapper.format_debug_string())
    if len(var.playlist) == 2:
        bot.async_download_next()
    return music_wrapper


def _headers_for_album(album_id):
    headers = dict(UA)
    headers['Referer'] = 'https://www.ximalaya.com/album/{}'.format(album_id)
    return headers


def _fetch_album_page(album_id, page_num):
    resp = requests.get(
        'https://www.ximalaya.com/revision/album/getTracksList',
        params={'albumId': album_id, 'pageNum': page_num, 'sort': 0},
        headers=_headers_for_album(album_id),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get('data', {})


def _parse_sound_url(text):
    """Return (track_id, 'track') if a sound URL, else (None, None)."""
    m = _SOUND_RE.search(text)
    if m:
        return m.group(1), 'track'
    return None, None


def _parse_album_url(text):
    """Return (album_id, 'album') if an album URL, else (None, None)."""
    m = _ALBUM_RE.search(text)
    if m:
        return m.group(1), 'album'
    return None, None


def _play_track(bot, user, text, track_id):
    music_wrapper = _queue_track(bot, user, track_id)
    _send(bot, text, "ximalaya_playing", song=music_wrapper.format_title())


def _play_album(bot, user, text, album_id):
    _send(bot, text, "ximalaya_album_loading")
    try:
        first_page = _fetch_album_page(album_id, 1)
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Could not fetch Ximalaya album %s", album_id)
        _send(bot, text, "ximalaya_play_error")
        return

    tracks = first_page.get('tracks', [])
    track_total = first_page.get('trackTotalCount', 0) or 0
    page_size = first_page.get('pageSize', 30) or 30
    album_title = ''
    count = 0

    if tracks:
        album_title = tracks[0].get('albumTitle', '') or album_title

    page_count = math.ceil(track_total / page_size) if track_total else 0
    if not page_count:
        _send(bot, text, "ximalaya_no_result")
        return

    for page_num in range(1, page_count + 1):
        if page_num == 1:
            page_data = first_page
        else:
            try:
                page_data = _fetch_album_page(album_id, page_num)
            except (requests.RequestException, ValueError, TypeError):
                log.warning(
                    "Could not fetch Ximalaya album page %d/%d",
                    page_num, page_count)
                continue

        for track in page_data.get('tracks', []):
            track_id = track.get('trackId')
            if not track_id:
                continue
            # Skip paid tracks in albums; validate() will fail for them anyway.
            _queue_track(
                bot,
                user,
                str(track_id),
                title=track.get('title', ''),
                artist=track.get('anchorName', ''),
            )
            count += 1

    _send(bot, text, "ximalaya_album_added", count=count,
          album=album_title or album_id)


def cmd_xm_dispatch(bot, user, text, command, parameter):
    """!xm <url_or_track_id> — play a single track or enqueue an album."""
    parameter = (parameter or '').strip()
    if not parameter:
        _send(bot, text, "ximalaya_usage", command=command)
        return

    if _NUMBER_RE.match(parameter):
        _play_track(bot, user, text, parameter)
        return

    track_id, kind = _parse_sound_url(parameter)
    if kind == 'track':
        _play_track(bot, user, text, track_id)
        return

    album_id, kind = _parse_album_url(parameter)
    if kind == 'album':
        _play_album(bot, user, text, album_id)
        return

    _send(bot, text, "ximalaya_usage", command=command)


def cmd_xm_play(bot, user, text, command, parameter):
    """Play a single Ximalaya track (kept for backward compatibility)."""
    parameter = (parameter or '').strip()
    if not parameter:
        _send(bot, text, "bad_parameter", command=command)
        return
    track_id, kind = _parse_sound_url(parameter)
    if not kind:
        if _NUMBER_RE.match(parameter):
            track_id = parameter
            kind = 'track'
    if kind != 'track':
        _send(bot, text, "ximalaya_usage", command=command)
        return
    _play_track(bot, user, text, track_id)


def cmd_xm_add(bot, user, text, command, parameter):
    """Add a single Ximalaya track to the queue (kept for backward compat)."""
    parameter = (parameter or '').strip()
    if not parameter:
        _send(bot, text, "bad_parameter", command=command)
        return
    track_id, kind = _parse_sound_url(parameter)
    if not kind:
        if _NUMBER_RE.match(parameter):
            track_id = parameter
            kind = 'track'
    if kind != 'track':
        _send(bot, text, "ximalaya_usage", command=command)
        return
    _queue_track(bot, user, track_id)
    _send(bot, text, "ximalaya_added", song=track_id)
