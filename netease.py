# coding=utf-8
"""Client helpers for NeteaseCloudMusicApi."""

import base64
import logging
import os

import requests


log = logging.getLogger("bot")


class NeteaseClient:
    def __init__(self, api_base_url):
        self.api_base_url = (api_base_url or "").rstrip("/")
        self.timeout = 10

    def _get(self, endpoint, params=None):
        if not self.api_base_url:
            raise ValueError("Netease API URL is empty")
        response = requests.get(
            self.api_base_url + endpoint,
            params=params or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Netease API response")
        return payload

    @staticmethod
    def _artists(value):
        artists = value or []
        return ", ".join(
            str(item.get("name", "")) for item in artists if isinstance(item, dict)
        )

    @classmethod
    def _song(cls, song):
        if not isinstance(song, dict):
            return None
        album = song.get("album") or song.get("al") or {}
        return {
            "id": song.get("id"),
            "name": song.get("name", ""),
            "artist": cls._artists(song.get("artists") or song.get("ar")),
            "album": album.get("name", "") if isinstance(album, dict) else "",
            "cover": album.get("picUrl") if isinstance(album, dict) else None,
            "duration": song.get("duration", song.get("dt")),
            "fee": song.get("fee"),
        }

    def search(self, keywords, limit=10):
        payload = self._get("/search", {"keywords": keywords, "limit": limit})
        songs = ((payload.get("result") or {}).get("songs") or [])
        return [item for item in (self._song(song) for song in songs) if item]

    def get_song_url(self, song_id, cookie=None):
        params = {"id": song_id}
        if cookie:
            params["cookie"] = cookie
        payload = self._get("/song/url", params)
        data = payload.get("data") or []
        if not data or not isinstance(data[0], dict):
            return None
        return data[0].get("url") or None

    def search_playlist(self, keywords):
        payload = self._get(
            "/search",
            {"keywords": keywords, "type": 1000},
        )
        playlists = ((payload.get("result") or {}).get("playlists") or [])
        return [
            {"id": item.get("id"), "name": item.get("name", "")}
            for item in playlists
            if isinstance(item, dict) and item.get("id") is not None
        ]

    def get_playlist_tracks(self, playlist_id):
        payload = self._get("/playlist/track/all", {"id": playlist_id})
        songs = payload.get("songs") or []
        result = []
        for song in songs:
            item = self._song(song)
            if item:
                result.append({
                    "id": item["id"],
                    "name": item["name"],
                    "artist": item["artist"],
                })
        return result

    def get_song_detail(self, song_id):
        payload = self._get("/song/detail", {"ids": song_id})
        songs = payload.get("songs") or []
        return self._song(songs[0]) if songs else None

    def qr_login_start(self):
        key_payload = self._get("/login/qr/key")
        key = (key_payload.get("data") or {}).get("unikey")
        if not key:
            raise ValueError("Netease QR key is missing")
        qr_payload = self._get(
            "/login/qr/create",
            {"key": key, "qrimg": "true"},
        )
        qrimg = (qr_payload.get("data") or {}).get("qrimg")
        if not qrimg:
            raise ValueError("Netease QR image is missing")
        if "," in qrimg:
            qrimg = qrimg.split(",", 1)[1]
        return key, qrimg

    def qr_login_check(self, key):
        payload = self._get("/login/qr/check", {"key": key})
        return payload.get("code"), payload.get("cookie")


class NeteaseCookieManager:
    def __init__(self, cookie_file):
        cookie_file = cookie_file or "config/netease_cookie.txt"
        if not os.path.isabs(cookie_file):
            cookie_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), cookie_file)
        self.cookie_file = cookie_file

    def get_cookie(self):
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as file:
                return file.read().strip() or None
        except FileNotFoundError:
            return None
        except OSError:
            log.exception("Could not read Netease cookie file: %s", self.cookie_file)
            return None

    def set_cookie(self, cookie):
        if not cookie:
            return
        parent = os.path.dirname(self.cookie_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.cookie_file, "w", encoding="utf-8") as file:
            file.write(cookie.strip())

    def clear_cookie(self):
        try:
            os.remove(self.cookie_file)
        except FileNotFoundError:
            pass
        except OSError:
            log.exception("Could not remove Netease cookie file: %s", self.cookie_file)
