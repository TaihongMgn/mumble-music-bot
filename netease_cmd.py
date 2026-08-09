# coding=utf-8
"""Mumble commands for Netease Cloud Music."""

import base64
import html
import logging
import os
import threading
import time

import requests

from constants import tr_cli as tr
from media.cache import get_cached_wrapper_from_scrap
import variables as var
from netease import NeteaseClient, NeteaseCookieManager


log = logging.getLogger("bot")

__all__ = [
    "cmd_yun_dispatch",
    "cmd_yun_play",
    "cmd_yun_add",
    "cmd_yun_search",
    "cmd_yun_playid",
    "cmd_yun_addid",
    "cmd_yun_gedan",
    "cmd_yun_gedanid",
    "cmd_yun_login",
]


def _config(option, fallback=""):
    try:
        return var.config.get("netease", option, fallback=fallback)
    except (AttributeError, KeyError):
        return fallback


def _client():
    return NeteaseClient(_config("api_url", "http://netease-api:3000"))


def _cookie_manager():
    return NeteaseCookieManager(_config("cookie_file", "config/netease_cookie.txt"))


def _search_limit():
    try:
        return max(1, int(_config("default_search_limit", "10")))
    except ValueError:
        return 10


def _send(bot, text, key, **kwargs):
    bot.send_msg(tr(key, **kwargs), text)


def _song_label(song):
    if not song:
        return ""
    artist = song.get("artist") or ""
    return "{} - {}".format(song.get("name", ""), artist)


def _queue_url(bot, user, url, title=""):
    music_wrapper = get_cached_wrapper_from_scrap(
        type="radio", url=url, name=title, user=user)
    var.playlist.append(music_wrapper)
    log.info("cmd: add Netease item to playlist: %s", music_wrapper.format_debug_string())
    if len(var.playlist) == 2:
        bot.async_download_next()
    return music_wrapper


def _song_url(client, song_id):
    return client.get_song_url(song_id, _cookie_manager().get_cookie())


def _search_first(bot, user, text, keywords):
    _send(bot, text, "netease_searching")
    try:
        results = _client().search(keywords, _search_limit())
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Netease search failed")
        _send(bot, text, "netease_search_error")
        return None
    if not results:
        _send(bot, text, "netease_no_result")
        return None
    return results[0]


def _play_or_add_song(bot, user, text, command, song, add_only=False):
    client = _client()
    try:
        url = _song_url(client, song.get("id"))
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Could not get Netease song URL")
        url = None
    if not url:
        _send(bot, text, "netease_play_error")
        return
    try:
        _queue_url(bot, user, url, title=_song_label(song))
    except Exception:
        log.exception("Could not add Netease song to playlist")
        _send(bot, text, "netease_play_error")
        return
    _send(bot, text, "netease_added" if add_only else "netease_playing", song=song.get("name", ""), artist=song.get("artist", ""))


def cmd_yun_play(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    song = _search_first(bot, user, text, parameter.strip())
    if song:
        _play_or_add_song(bot, user, text, command, song, add_only=False)


def cmd_yun_add(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    song = _search_first(bot, user, text, parameter.strip())
    if song:
        _play_or_add_song(bot, user, text, command, song, add_only=True)


def cmd_yun_search(bot, user, text, command, parameter):
    global log
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    _send(bot, text, "netease_searching")
    try:
        client = _client()
        results = client.search(parameter.strip(), _search_limit())
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Netease search failed")
        _send(bot, text, "netease_search_error")
        return
    if not results:
        _send(bot, text, "netease_no_result")
        return

    import command as command_module
    command_module.song_shortlist = []
    rows = ["<table><tr><th>{}</th><th>{}</th><th>{}</th><th>{}</th></tr>".format(tr("netease_index"), tr("netease_song"), tr("netease_artist"), tr("netease_status"))]
    for song in results:
        url = None
        try:
            url = _song_url(client, song.get("id"))
        except (requests.RequestException, ValueError, TypeError):
            log.warning("Could not resolve Netease song URL: %s", song.get("id"))
        if url:
            command_module.song_shortlist.append({
                "type": "url",
                "url": url,
                "title": _song_label(song),
            })
            index = len(command_module.song_shortlist)
            status = tr("netease_available")
        else:
            index = "-"
            status = tr("netease_requires_login")
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                index,
                html.escape(song.get("name", "")),
                html.escape(song.get("artist", "")),
                status,
            )
        )
    rows.append("</table>")
    if command_module.song_shortlist:
        rows.append(tr("shortlist_instruction"))
    bot.send_msg("".join(rows), text)


def _song_by_id(bot, user, text, song_id):
    try:
        song = _client().get_song_detail(song_id)
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Could not get Netease song detail")
        song = None
    if not song:
        song = {"id": song_id, "name": str(song_id), "artist": ""}
    return song


def cmd_yun_playid(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    song = _song_by_id(bot, user, text, parameter.strip())
    _play_or_add_song(bot, user, text, command, song, add_only=False)


def cmd_yun_addid(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    song = _song_by_id(bot, user, text, parameter.strip())
    _play_or_add_song(bot, user, text, command, song, add_only=True)


def cmd_yun_gedan(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    _send(bot, text, "netease_playlist_loading")
    try:
        playlists = _client().search_playlist(parameter.strip())
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Netease playlist search failed")
        _send(bot, text, "netease_search_error")
        return
    if not playlists:
        _send(bot, text, "netease_no_result")
        return
    cmd_yun_gedanid(bot, user, text, command, str(playlists[0]["id"]))


def cmd_yun_gedanid(bot, user, text, command, parameter):
    if not parameter.strip():
        _send(bot, text, "bad_parameter", command=command)
        return
    _send(bot, text, "netease_playlist_loading")
    try:
        client = _client()
        tracks = client.get_playlist_tracks(parameter.strip())
    except (requests.RequestException, ValueError, TypeError):
        log.exception("Netease playlist loading failed")
        _send(bot, text, "netease_search_error")
        return
    if not tracks:
        _send(bot, text, "netease_no_result")
        return

    count = 0
    cookie = _cookie_manager().get_cookie()
    for track in tracks:
        try:
            url = client.get_song_url(track.get("id"), cookie)
            if url:
                _queue_url(bot, user, url)
                count += 1
        except (requests.RequestException, ValueError, TypeError):
            log.warning("Could not add Netease playlist track: %s", track.get("id"))
    if count:
        _send(bot, text, "netease_playlist_added", count=count)
    else:
        _send(bot, text, "netease_play_error")


def _qr_image_path():
    image_path = _config("qr_image_path", "music/qr_login.png")
    if not os.path.isabs(image_path):
        image_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), image_path)
    return image_path


def _web_qr_url():
    address = _config("web_url", "") or "http://127.0.0.1:8181"
    try:
        address = var.config.get("webinterface", "access_address", fallback=address)
    except (AttributeError, KeyError):
        pass
    return address.rstrip("/") + "/netease/qr_login.png"


def cmd_yun_login(bot, user, text, command, parameter):
    try:
        client = _client()
        key, qrimg_base64 = client.qr_login_start()
        image_path = _qr_image_path()
        parent = os.path.dirname(image_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(image_path, "wb") as image_file:
            image_file.write(base64.b64decode(qrimg_base64))
    except (requests.RequestException, ValueError, TypeError, OSError):
        log.exception("Could not create Netease login QR code")
        _send(bot, text, "netease_play_error")
        return

    _send(bot, text, "netease_login_qr", url=_web_qr_url())
    _send(bot, text, "netease_login_waiting")

    def poll_login():
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                status_code, cookie = client.qr_login_check(key)
                if int(status_code or 0) == 803:
                    if cookie:
                        _cookie_manager().set_cookie(cookie)
                    _send(bot, text, "netease_login_success")
                    return
            except (requests.RequestException, ValueError, TypeError):
                log.warning("Netease QR login polling failed", exc_info=True)
            time.sleep(2)
        _send(bot, text, "netease_login_timeout")

    thread = threading.Thread(target=poll_login, name="NeteaseQRLogin", daemon=True)
    thread.start()


def cmd_yun_help(bot, user, text, command, parameter):
    _send(bot, text, "netease_help")


def cmd_yun_dispatch(bot, user, text, command, parameter):
    parts = parameter.strip().split(maxsplit=1)
    if not parts:
        cmd_yun_help(bot, user, text, command, parameter)
        return
    action = parts[0].lower()
    argument = parts[1] if len(parts) > 1 else ""
    handlers = {
        "play": cmd_yun_play,
        "add": cmd_yun_add,
        "search": cmd_yun_search,
        "playid": cmd_yun_playid,
        "addid": cmd_yun_addid,
        "gedan": cmd_yun_gedan,
        "gedanid": cmd_yun_gedanid,
        "login": cmd_yun_login,
        "help": cmd_yun_help,
    }
    handler = handlers.get(action)
    if handler is None:
        cmd_yun_help(bot, user, text, command, parameter)
        return
    handler(bot, user, text, command, argument)
