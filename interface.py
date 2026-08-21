#!/usr/bin/python3
import base64
import sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, send_file, Response, jsonify, abort, session
from werkzeug.utils import secure_filename

import variables as var
import util
import math
import os
import os.path
import errno
import re
from typing import Type
import media
import json
from media.item import dicts_to_items, dict_to_item, BaseItem
from media.file import FileItem
from media.url import URLItem
from media.url_from_playlist import PlaylistURLItem
from media.radio import RadioItem
from media.netease_item import NeteaseItem
from media.ximalaya_item import XimalayaItem
from media.cache import get_cached_wrapper_from_scrap, get_cached_wrapper_by_id, get_cached_wrappers_by_tags, \
    get_cached_wrapper
from database import MusicDatabase, Condition
from constants import tr_web
from netease import NeteaseClient, NeteaseCookieManager
import logging
import time
import requests
import secrets


class ReverseProxied(object):
    """Wrap the application in this middleware and configure the
    front-end server to add these headers, to let you quietly bind
    this to a URL other than / and to an HTTP scheme that is
    different than what is used locally.

    In nginx:
    location /myprefix {
        proxy_pass http://192.168.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Scheme $scheme;
        proxy_set_header X-Script-Name /myprefix;
        }

    :param app: the WSGI application
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]

        scheme = environ.get('HTTP_X_SCHEME', '')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        real_ip = environ.get('HTTP_X_REAL_IP', '')
        if real_ip:
            environ['REMOTE_ADDR'] = real_ip
        return self.app(environ, start_response)


root_dir = os.path.dirname(__file__)
web = Flask(__name__, template_folder=os.path.join(root_dir, "web/templates"))
# A random fallback keeps session signing safe when no persistent secret is configured.
web.secret_key = secrets.token_hex(32)
web.config['SESSION_COOKIE_HTTPONLY'] = True
web.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
#web.config['TEMPLATES_AUTO_RELOAD'] = True
log = logging.getLogger("bot")
user = 'Remote Control'
netease_qr_login_keys = {}


def init_proxy():
    global web
    if var.is_proxified:
        web.wsgi_app = ReverseProxied(web.wsgi_app)


# https://stackoverflow.com/questions/29725217/password-protect-one-webpage-in-flask-app


def _get_web_users():
    try:
        return json.loads(var.db.get("privilege", "web_access", fallback='[]'))
    except (TypeError, ValueError, AttributeError):
        return []


def _admin_username():
    return var.config.get("webinterface", "user", fallback="")


def _is_admin(username):
    return bool(username) and username == _admin_username()


def _session_user_is_valid(username):
    if not username:
        return False
    return _is_admin(username) or username in _get_web_users()


def check_auth(username, password):
    """Return whether a web username/password combination is valid."""
    if username and username == _admin_username() and password == var.config.get("webinterface", "password", fallback=""):
        return True

    if username not in _get_web_users():
        return False

    try:
        user_dict = json.loads(var.db.get("user", username, fallback='{}'))
        return bool(
            'password' in user_dict and 'salt' in user_dict
            and util.verify_password(password, user_dict['password'], user_dict['salt'])
        )
    except (TypeError, ValueError, AttributeError, KeyError):
        return False


def authenticate():
    """Send the legacy HTTP Basic Auth challenge."""
    return Response('Could not verify your access level for that URL.\n'
                    'You have to login with proper credentials', 401,
                    {'WWW-Authenticate': 'Basic realm="Login Required"'})


BAD_ACCESS_BAN_SECONDS = 5 * 60
bad_access_count = {}
banned_ip = {}


def _client_ip():
    return request.remote_addr or 'unknown'


def _max_attempts():
    return var.config.getint("webinterface", "max_attempts", fallback=10)


def _cleanup_banned_ips():
    now = time.time()
    for ip, banned_at in list(banned_ip.items()):
        if now - banned_at >= BAD_ACCESS_BAN_SECONDS:
            banned_ip.pop(ip, None)
            bad_access_count.pop(ip, None)


def _is_ip_banned(ip=None):
    _cleanup_banned_ips()
    return (ip or _client_ip()) in banned_ip


def _record_failed_access(ip=None):
    ip = ip or _client_ip()
    count = bad_access_count.get(ip, 0) + 1
    bad_access_count[ip] = count
    log.info("web: failed authentication attempt from ip %s (%d attempts).", ip, count)
    if count > _max_attempts():
        banned_ip[ip] = time.time()
        log.info("web: access banned for %s for %d seconds.", ip, BAD_ACCESS_BAN_SECONDS)
    return count


def _reset_failed_access(ip=None):
    ip = ip or _client_ip()
    bad_access_count.pop(ip, None)
    banned_ip.pop(ip, None)


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        global user

        ip = _client_ip()
        if _is_ip_banned(ip):
            abort(403)

        auth_method = var.config.get("webinterface", "auth_method", fallback="none")

        if auth_method == 'session':
            session_user = session.get('user')
            if _session_user_is_valid(session_user):
                user = session_user
                return f(*args, **kwargs)
            session.pop('user', None)
            return redirect('/login')

        if auth_method == 'password':
            auth = request.authorization
            if auth:
                user = auth.username
                if check_auth(auth.username, auth.password):
                    return f(*args, **kwargs)
                _record_failed_access(ip)
                return authenticate()
            return authenticate()

        if auth_method == 'token':
            if 'user' in session and 'token' not in request.args:
                user = session['user']
                return f(*args, **kwargs)
            elif 'token' in request.args:
                token = request.args.get('token')
                token_user = var.db.get("web_token", token, fallback=None)
                if token_user is not None:
                    user = token_user

                    user_info = var.db.get("user", user, fallback=None)
                    user_dict = json.loads(user_info)
                    user_dict['IP'] = ip
                    var.db.set("user", user, json.dumps(user_dict))

                    log.debug(
                        "web: new user access, token validated for the user: %s, from ip %s.",
                        token_user, ip)
                    session['token'] = token
                    session['user'] = token_user
                    return f(*args, **kwargs)

            _record_failed_access(ip)
            return render_template(f'need_token.{var.language}.html',
                                   name=var.config.get('bot', 'username'),
                                   command=f"{var.config.get('commands', 'command_symbol')[0]}"
                                           f"{var.config.get('commands', 'requests_webinterface_access')}")

        return f(*args, **kwargs)

    return decorated


def tag_color(tag):
    num = hash(tag) % 8
    if num == 0:
        return "primary"
    elif num == 1:
        return "secondary"
    elif num == 2:
        return "success"
    elif num == 3:
        return "danger"
    elif num == 4:
        return "warning"
    elif num == 5:
        return "info"
    elif num == 6:
        return "light"
    elif num == 7:
        return "dark"


def build_tags_color_lookup():
    color_lookup = {}
    for tag in var.music_db.query_all_tags():
        color_lookup[tag] = tag_color(tag)

    return color_lookup


def get_all_dirs():
    dirs = ["."]
    paths = var.music_db.query_all_paths()
    for path in paths:
        pos = 0
        while True:
            pos = path.find("/", pos + 1)
            if pos == -1:
                break
            folder = path[:pos]
            if folder not in dirs:
                dirs.append(folder)

    return dirs


def _render_login_page(**context):
    context.setdefault('is_admin', _is_admin(session.get('user')))
    context.setdefault('session_user', session.get('user'))
    context.setdefault('register_form', False)
    context.setdefault('register_username', '')
    return render_template('login.html', tr=tr_web, **context)


@web.route('/login', methods=['GET', 'POST'])
def login():
    ip = _client_ip()
    if _is_ip_banned(ip):
        abort(403)

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not check_auth(username, password):
            _record_failed_access(ip)
            return _render_login_page(error=tr_web('login_failed'), username=username), 200

        _reset_failed_access(ip)
        session.clear()
        session['user'] = username
        return redirect('/')

    return _render_login_page()


@web.route('/logout', methods=['GET'])
def logout():
    session.clear()
    return redirect('/login')


@web.route('/register', methods=['GET', 'POST'])
def register():
    ip = _client_ip()
    if _is_ip_banned(ip):
        abort(403)

    if not _is_admin(session.get('user')):
        _record_failed_access(ip)
        return redirect('/login')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        error = None
        web_users = _get_web_users()

        if not re.fullmatch(r'[A-Za-z0-9_]+', username):
            error = tr_web('username_invalid')
        elif len(password) < 6:
            error = tr_web('password_too_short')
        elif password != confirm:
            error = tr_web('password_mismatch')
        elif username == _admin_username() or username in web_users:
            error = tr_web('username_exists')

        if error:
            _record_failed_access(ip)
            return _render_login_page(
                register_form=True,
                register_error=error,
                register_username=username), 400

        user_dict = {}
        try:
            user_dict = json.loads(var.db.get('user', username, fallback='{}'))
        except (TypeError, ValueError):
            user_dict = {}
        if not isinstance(user_dict, dict):
            user_dict = {}
        user_dict['password'], user_dict['salt'] = util.get_salted_password_hash(password)
        web_users.append(username)
        var.db.set('privilege', 'web_access', json.dumps(web_users))
        var.db.set('user', username, json.dumps(user_dict))
        _reset_failed_access(ip)
        return _render_login_page(register_form=True, register_success=tr_web('register_success'))

    return _render_login_page(register_form=True)


@web.route("/", methods=['GET'])
@requires_auth
def index():
    html = open(os.path.join(root_dir, f"web/templates/index.{var.language}.html"), "r").read()
    response = Response(html, mimetype='text/html; charset=utf-8')
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@web.route("/api/session_user", methods=['GET'])
@requires_auth
def api_session_user():
    return jsonify({'user': user or '', 'is_admin': _is_admin(user or '')})


def _require_admin():
    if not _is_admin(user or ''):
        abort(403)


@web.route("/api/accounts", methods=['GET'])
@requires_auth
def api_accounts_list():
    _require_admin()
    users = _get_web_users()
    result = []
    admin_user = _admin_username()
    for username in users:
        result.append({'username': username, 'role': 'admin' if username == admin_user else 'user'})
    return jsonify({'accounts': result})


@web.route("/api/accounts/register", methods=['POST'])
@requires_auth
def api_accounts_register():
    _require_admin()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    confirm = str(payload.get('confirm_password', ''))
    web_users = _get_web_users()

    if not re.fullmatch(r'[A-Za-z0-9_]+', username):
        return jsonify({'error': tr_web('username_invalid')}), 400
    if len(password) < 6:
        return jsonify({'error': tr_web('password_too_short')}), 400
    if password != confirm:
        return jsonify({'error': tr_web('password_mismatch')}), 400
    if username == _admin_username() or username in web_users:
        return jsonify({'error': tr_web('username_exists')}), 400

    user_dict = {}
    try:
        user_dict = json.loads(var.db.get('user', username, fallback='{}'))
    except (TypeError, ValueError):
        user_dict = {}
    if not isinstance(user_dict, dict):
        user_dict = {}
    user_dict['password'], user_dict['salt'] = util.get_salted_password_hash(password)
    web_users.append(username)
    var.db.set('privilege', 'web_access', json.dumps(web_users))
    var.db.set('user', username, json.dumps(user_dict))
    return jsonify({'success': True})


@web.route("/api/accounts/delete", methods=['POST'])
@requires_auth
def api_accounts_delete():
    _require_admin()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username', '')).strip()
    if not username or username == _admin_username():
        return jsonify({'error': tr_web('cannot_delete_admin')}), 400
    web_users = _get_web_users()
    if username not in web_users:
        return jsonify({'error': tr_web('username_not_found')}), 400
    web_users.remove(username)
    var.db.set('privilege', 'web_access', json.dumps(web_users))
    var.db.set('user', username, json.dumps({}))
    return jsonify({'success': True})



@web.route("/playlist", methods=['GET'])
@requires_auth
def playlist():
    if len(var.playlist) == 0:
        return jsonify({
            'items': [],
            'current_index': -1,
            'length': 0,
            'start_from': 0
        })

    DEFAULT_DISPLAY_COUNT = 11
    _from = 0
    _to = 10

    if 'range_from' in request.args and 'range_to' in request.args:
        _from = int(request.args['range_from'])
        _to = int(request.args['range_to'])
    else:
        if var.playlist.current_index - int(DEFAULT_DISPLAY_COUNT / 2) > 0:
            _from = var.playlist.current_index - int(DEFAULT_DISPLAY_COUNT / 2)
            _to = _from - 1 + DEFAULT_DISPLAY_COUNT

    tags_color_lookup = build_tags_color_lookup()  # TODO: cached this?
    items = []

    for index, item_wrapper in enumerate(var.playlist[_from: _to + 1]):
        tag_tuples = []
        for tag in item_wrapper.item().tags:
            tag_tuples.append([tag, tags_color_lookup[tag]])

        item: Type[BaseItem] = item_wrapper.item()

        title = item.format_title()
        artist = "??"
        path = ""
        duration = 0
        if isinstance(item, FileItem):
            path = item.path
            if item.artist:
                artist = item.artist
            duration = item.duration
        elif isinstance(item, NeteaseItem):
            artist = item.artist or "??"
            duration = item.duration
        elif isinstance(item, XimalayaItem):
            artist = item.artist or "??"
            duration = item.duration
        elif isinstance(item, URLItem):
            path = f" <a href=\"{item.url}\"><i>{item.url}</i></a>"
            duration = item.duration
        elif isinstance(item, PlaylistURLItem):
            path = f" <a href=\"{item.url}\"><i>{item.url}</i></a>"
            artist = f" <a href=\"{item.playlist_url}\"><i>{item.playlist_title}</i></a>"
            duration = item.duration
        elif isinstance(item, RadioItem):
            path = f" <a href=\"{item.url}\"><i>{item.url}</i></a>"

        thumb = ""
        if item.type != 'radio' and item.thumbnail:
            thumb = f"data:image/PNG;base64,{item.thumbnail}"
        else:
            thumb = "static/image/unknown-album.png"

        items.append({
            'index': _from + index,
            'id': item.id,
            'type': item.display_type(),
            'path': path,
            'title': title,
            'artist': artist,
            'user': item_wrapper.user or '',
            'thumbnail': thumb,
            'tags': tag_tuples,
            'duration': duration
        })

    return jsonify({
        'items': items,
        'current_index': var.playlist.current_index,
        'length': len(var.playlist),
        'start_from': _from
    })


def status():
    if len(var.playlist) > 0:
        return jsonify({'ver': var.playlist.version,
                        'current_index': var.playlist.current_index,
                        'empty': False,
                        'play': not var.bot.is_pause,
                        'mode': var.playlist.mode,
                        'volume': var.bot.volume_helper.plain_volume_set,
                        'playhead': var.bot.playhead
                        })

    else:
        return jsonify({'ver': var.playlist.version,
                        'current_index': var.playlist.current_index,
                        'empty': True,
                        'play': not var.bot.is_pause,
                        'mode': var.playlist.mode,
                        'volume': var.bot.volume_helper.plain_volume_set,
                        'playhead': 0
                        })




@web.route("/api/netease/search", methods=['GET'])
@requires_auth
def netease_search():
    keywords = request.args.get('keywords', '').strip()
    if not keywords:
        return jsonify({'songs': []})
    try:
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        limit = var.config.getint('netease', 'default_search_limit', fallback=10)
        results = client.search(keywords, limit)
        return jsonify({'songs': results})
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: Netease search failed")
        return jsonify({'songs': [], 'error': tr_web('netease_search_error')}), 502

_XM_SOUND_RE = re.compile(r'ximalaya\.com/(?:\d+/)?sound/(\d+)', re.IGNORECASE)
_XM_ALBUM_RE = re.compile(r'ximalaya\.com/(?:\d+/)?album/(\d+)', re.IGNORECASE)
_XM_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'}


@web.route("/api/ximalaya/resolve", methods=['GET'])
def ximalaya_resolve():
    value = (request.args.get('value') or '').strip()
    if not value:
        return jsonify({'error': tr_web('ximalaya_web_error')}), 400
    m = _XM_SOUND_RE.search(value)
    if not m:
        m = _XM_ALBUM_RE.search(value)
        kind = 'album'
    else:
        kind = 'track'
    if not m and re.match(r'^\d+$', value):
        kind = 'track'
        track_id = value
    elif kind == 'track':
        track_id = m.group(1)
    elif kind == 'album':
        album_id = m.group(1)
    else:
        return jsonify({'error': tr_web('ximalaya_web_error')}), 400

    try:
        if kind == 'track':
            resp = requests.get(
                'https://m.ximalaya.com/tracks/{}.json'.format(track_id),
                headers=_XM_UA, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return jsonify({
                'kind': 'track',
                'track_id': track_id,
                'title': data.get('title', ''),
                'artist': data.get('nickname', ''),
                'duration': int(data.get('duration') or 0),
                'is_paid': bool(data.get('is_paid', False)),
            })
        else:
            # 翻页拉取全部曲目
            all_tracks = []
            page_num = 1
            album_title = ''
            while True:
                resp = requests.get(
                    'https://www.ximalaya.com/revision/album/getTracksList',
                    params={'albumId': album_id, 'pageNum': page_num, 'sort': 0},
                    headers={**_XM_UA, 'Referer': 'https://www.ximalaya.com/album/{}'.format(album_id)},
                    timeout=30)
                resp.raise_for_status()
                body = resp.json()
                data = body.get('data') or {}
                tracks = data.get('tracks') or []
                if not tracks:
                    break
                if not album_title and tracks:
                    album_title = tracks[0].get('albumTitle', '')
                for t in tracks:
                    all_tracks.append({
                        'track_id': str(t.get('trackId', '')),
                        'title': t.get('title', ''),
                        'duration': int(t.get('duration') or 0),
                        'is_paid': bool(t.get('isPaid', False)),
                    })
                page_size = int(data.get('pageSize') or 30)
                total = int(data.get('trackTotalCount') or 0)
                if page_num * page_size >= total or len(tracks) < page_size:
                    break
                page_num += 1
            return jsonify({
                'kind': 'album',
                'album_id': album_id,
                'album_title': album_title,
                'total': len(all_tracks),
                'tracks': all_tracks,
            })
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: ximalaya resolve failed")
        return jsonify({'error': tr_web('ximalaya_web_error')}), 502

# --- Ximalaya cookie management (simple functions, no class) ---
def _xm_cookie_file():
    # 容器内 /config 是 compose 挂载卷（持久化）；重建镜像不丢。
    # 本地开发/无挂载卷时回退到源码目录下相对路径。
    if os.path.isdir('/config'):
        return os.path.join('/config', 'ximalaya_cookie.txt')
    return os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        var.config.get('ximalaya', 'cookie_file', fallback='config/ximalaya_cookie.txt'))


def _xm_load_cookie():
    try:
        with open(_xm_cookie_file(), 'r', encoding='utf-8') as f:
            return f.read().strip()
    except (IOError, FileNotFoundError):
        return ''


def _xm_save_cookie(cookie_str):
    path = _xm_cookie_file()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(cookie_str.strip())


def _xm_parse_set_cookie(set_cookie_headers):
    """Parse multiple Set-Cookie header values into a single Cookie string."""
    cookies = {}
    for header in set_cookie_headers:
        parts = header.split(';')
        if parts and '=' in parts[0]:
            name, value = parts[0].strip().split('=', 1)
            cookies[name.strip()] = value.strip()
    return '; '.join('{}={}'.format(k, v) for k, v in cookies.items())


def _xm_merge_cookies(existing_cookie, new_cookie_str):
    """Merge new cookies into existing cookie string (new overwrites old)."""
    merged = {}
    for part in existing_cookie.split(';') if existing_cookie else []:
        if '=' in part:
            k, v = part.strip().split('=', 1)
            merged[k] = v
    for part in new_cookie_str.split(';') if new_cookie_str else []:
        if '=' in part:
            k, v = part.strip().split('=', 1)
            merged[k] = v
    return '; '.join('{}={}'.format(k, v) for k, v in merged.items())


def _xm_get_cookie_headers():
    cookie = _xm_load_cookie()
    if cookie:
        return {'Cookie': cookie}
    return {}


_XM_PASSPORT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
    'Referer': 'https://www.ximalaya.com/login',
    'Origin': 'https://www.ximalaya.com',
}

_XM_PASSPORT_SESSION = requests.Session()
_XM_PASSPORT_SESSION.headers.update(_XM_PASSPORT_HEADERS)

def _xm_passport_get(url, **kwargs):
    kwargs.pop('headers', None)
    return _XM_PASSPORT_SESSION.get(url, timeout=30, **kwargs)

_XM_QR_LOGIN_KEYS = {}


@web.route("/api/ximalaya/qr_start", methods=['POST'])
@requires_auth
def ximalaya_qr_start():
    try:
        resp = _xm_passport_get(
            'https://passport.ximalaya.com/web/qrCode/gen',
            params={'level': 'L', 'source': '???????'})
        resp.raise_for_status()
        data = resp.json()
        if data.get('ret') != 0:
            return jsonify({'error': tr_web('ximalaya_web_error')}), 502
        qr_id = data.get('qrId', '')
        qr_img = 'data:image/png;base64,' + data.get('img', '')
        now = time.time()
        for old_qr_id, created_at in list(_XM_QR_LOGIN_KEYS.items()):
            if now - created_at >= 300:
                _XM_QR_LOGIN_KEYS.pop(old_qr_id, None)
        _XM_QR_LOGIN_KEYS[qr_id] = now
        return jsonify({'ret': 0, 'qr_id': qr_id, 'qr_img': qr_img})
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: ximalaya qr_start failed")
        return jsonify({'error': tr_web('ximalaya_web_error')}), 502


@web.route("/api/ximalaya/qr_check", methods=['GET'])
@requires_auth
def ximalaya_qr_check():
    qr_id = (request.args.get('qr_id') or '').strip()
    created_at = _XM_QR_LOGIN_KEYS.get(qr_id)
    if not qr_id or created_at is None or time.time() - created_at >= 300:
        _XM_QR_LOGIN_KEYS.pop(qr_id, None)
        return jsonify({'ret': 32000, 'msg': ''})
    try:
        ts_ms = int(time.time() * 1000)
        resp = _xm_passport_get(
            'https://passport.ximalaya.com/web/qrCode/check/{}/{}'.format(qr_id, ts_ms))
        resp.raise_for_status()
        data = resp.json()
        ret = data.get('ret', 32000)
        if ret == 0:
            set_cookie_headers = []
            try:
                set_cookie_headers = resp.raw.headers.getlist('Set-Cookie')
            except (AttributeError, TypeError):
                pass
            if not set_cookie_headers:
                single = resp.headers.get('Set-Cookie', '')
                if single:
                    set_cookie_headers = [single]
            new_cookie = _xm_parse_set_cookie(set_cookie_headers)
            existing = _xm_load_cookie()
            merged = _xm_merge_cookies(existing, new_cookie)
            if merged:
                _xm_save_cookie(merged)
            _XM_QR_LOGIN_KEYS.pop(qr_id, None)
        return jsonify({'ret': ret, 'msg': data.get('msg', '')})
    except (requests.RequestException, ValueError, TypeError, KeyError):
        log.exception("web: ximalaya qr_check failed")
        return jsonify({'ret': 32000, 'msg': ''}), 502


@web.route("/api/ximalaya/account", methods=['GET'])
@requires_auth
def ximalaya_account():
    cookie = _xm_load_cookie()
    if not cookie:
        return jsonify({'logged_in': False})
    try:
        resp = requests.get(
            'https://www.ximalaya.com/revision/main/getCurrentUser',
            headers={'User-Agent': _XM_PASSPORT_HEADERS['User-Agent'],
                     'Cookie': cookie},
            timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get('ret') in (0, 200) and data.get('data'):
            info = data['data']
            avatar = info.get('logoPic', '') or info.get('avatar', '') or info.get('avatarUrl', '')
            if avatar.startswith('//'):
                avatar = 'https:' + avatar
            return jsonify({
                'logged_in': True,
                'nickname': info.get('nickname', ''),
                'avatar': avatar,
                'uid': info.get('uid', ''),
            })
        return jsonify({'logged_in': False})
    except (requests.RequestException, ValueError, TypeError, KeyError):
        log.exception("web: ximalaya account check failed")
        return jsonify({'logged_in': False})


@web.route("/api/ximalaya/logout", methods=['POST'])
@requires_auth
def ximalaya_logout():
    _xm_save_cookie('')
    return jsonify({'success': True})


def _extract_netease_playlist_id(value):
    value = str(value or '').strip()
    if value.isdigit():
        return value
    match = re.search(r'id=(\d+)', value)
    return match.group(1) if match else None


def _get_netease_qr_image_path():
    image_path = var.config.get('netease', 'qr_image_path', fallback='music/qr_login.png')
    if not os.path.isabs(image_path):
        image_path = os.path.join(root_dir, image_path)
    return image_path


def _get_netease_cookie_manager():
    return NeteaseCookieManager(
        var.config.get('netease', 'cookie_file', fallback='config/netease_cookie.txt'))


def _get_netease_client_and_cookie():
    client = NeteaseClient(var.config.get('netease', 'api_url'))
    return client, _get_netease_cookie_manager().get_cookie()


@web.route("/api/netease/account", methods=['GET'])
@requires_auth
def netease_account():
    try:
        client, cookie = _get_netease_client_and_cookie()
        status = client.login_status(cookie) if cookie else None
        profile = (status or {}).get('profile') or {}
        account = (status or {}).get('account') or {}
        try:
            listening_seconds = int(float(
                var.db.get('netease', 'total_listening_seconds', fallback='0') or 0))
        except (TypeError, ValueError):
            listening_seconds = 0
        return jsonify({
            'logged_in': bool(status and status.get('logged_in')),
            'nickname': profile.get('nickname') or account.get('nickname') or '',
            'avatar': profile.get('avatarUrl') or profile.get('avatar') or None,
            'listening_seconds': listening_seconds,
            'listening_hours': round(listening_seconds / 3600, 1),
        })
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: Netease account loading failed")
        return jsonify({'error': 'Netease account loading failed'}), 502


@web.route("/api/netease/qr_start", methods=['POST'])
@requires_auth
def netease_qr_start():
    try:
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        key, qrimg_base64 = client.qr_login_start()
        image_path = _get_netease_qr_image_path()
        parent = os.path.dirname(image_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(image_path, "wb") as image_file:
            image_file.write(base64.b64decode(qrimg_base64))
        now = time.time()
        for old_key, created_at in list(netease_qr_login_keys.items()):
            if now - created_at >= 300:
                netease_qr_login_keys.pop(old_key, None)
        netease_qr_login_keys[key] = now
        return jsonify({
            'qr_url': f"/netease/qr_login.png?t={int(now * 1000)}",
            'key': key,
        })
    except (requests.RequestException, ValueError, TypeError, OSError):
        log.exception("web: Could not create Netease login QR code")
        return jsonify({'error': 'Could not create Netease login QR code'}), 502


def _netease_qr_message(code):
    if code == 801:
        return tr_web('netease_qr_waiting')
    if code == 802:
        return tr_web('netease_qr_scanned')
    if code == 803:
        return tr_web('netease_qr_success')
    return tr_web('netease_qr_expired')


@web.route("/api/netease/qr_check", methods=['GET'])
@requires_auth
def netease_qr_check():
    key = request.args.get('key', '').strip()
    created_at = netease_qr_login_keys.get(key)
    if not key or created_at is None or time.time() - created_at >= 300:
        netease_qr_login_keys.pop(key, None)
        return jsonify({'code': 800, 'message': _netease_qr_message(800)})
    try:
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        code, cookie = client.qr_login_check(key)
        code = int(code or 0)
        if code == 803:
            if cookie:
                _get_netease_cookie_manager().set_cookie(cookie)
            netease_qr_login_keys.pop(key, None)
        return jsonify({'code': code, 'message': _netease_qr_message(code)})
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: Netease QR login check failed")
        return jsonify({'error': 'Netease QR login check failed'}), 502


@web.route("/api/netease/logout", methods=['POST'])
@requires_auth
def netease_logout():
    _get_netease_cookie_manager().clear_cookie()
    return jsonify({'success': True})


def _add_netease_listening_time(duration_ms):
    try:
        seconds = int(round(float(duration_ms or 0) / 1000))
    except (TypeError, ValueError):
        return
    if seconds <= 0:
        return
    try:
        total = int(float(var.db.get('netease', 'total_listening_seconds', fallback='0') or 0))
    except (TypeError, ValueError):
        total = 0
    var.db.set('netease', 'total_listening_seconds', str(total + seconds))


def _add_netease_tracks(client, cookie, tracks, playlist_user):
    added = 0
    skipped = 0
    duration_ms_total = 0
    should_start_download = False
    for batch_start in range(0, len(tracks), 50):
        for track in tracks[batch_start:batch_start + 50]:
            song_id = track.get('id') if isinstance(track, dict) else None
            if not song_id:
                skipped += 1
                continue
            title = (track.get('name', '') or '') if isinstance(track, dict) else ''
            artist = (track.get('artist', '') or '') if isinstance(track, dict) else ''
            # Probe availability here so unavailable/VIP tracks are not queued.
            try:
                url = client.get_song_url(song_id, cookie)
            except (requests.RequestException, ValueError, TypeError):
                log.warning("Could not get Netease song URL: %s", song_id)
                skipped += 1
                continue
            if not url:
                skipped += 1
                continue
            try:
                music_wrapper = get_cached_wrapper_from_scrap(
                    type='netease',
                    song_id=song_id,
                    title=title,
                    artist=artist,
                    user=playlist_user)
                var.playlist.append(music_wrapper)
                added += 1
                try:
                    duration_ms_total += float(track.get('duration') or 0)
                except (TypeError, ValueError):
                    pass
                if len(var.playlist) == 2:
                    should_start_download = True
                log.info("web: add Netease playlist item to playlist: " +
                         music_wrapper.format_debug_string())
            except Exception:
                log.exception("web: could not add Netease playlist track: %s", song_id)
                skipped += 1
    if should_start_download:
        var.bot.async_download_next()
    if duration_ms_total > 0:
        _add_netease_listening_time(duration_ms_total)
    return added, skipped


@web.route("/api/netease/playlist", methods=['GET'])
@requires_auth
def netease_playlist():
    playlist_id = _extract_netease_playlist_id(request.args.get('id') or request.args.get('url'))
    if not playlist_id:
        return jsonify({'error': tr_web('netease_playlist_no_result')}), 400
    try:
        client = NeteaseClient(var.config.get('netease', 'api_url'))
        detail = client.get_playlist_detail(playlist_id)
        songs = client.get_playlist_tracks(playlist_id)
    except (requests.RequestException, ValueError, TypeError):
        log.exception("web: Netease playlist loading failed")
        return jsonify({'error': tr_web('netease_playlist_error')}), 502
    if not detail.get('name') and not songs:
        return jsonify({'error': tr_web('netease_playlist_no_result')}), 404
    return jsonify({
        'id': str(detail.get('id') or playlist_id),
        'name': detail.get('name', ''),
        'cover': detail.get('cover'),
        'songs': songs,
    })


@web.route("/api/netease/playlists", methods=['GET'])
@requires_auth
def netease_playlists():
    conn = sqlite3.connect(var.db.db_path)
    try:
        rows = conn.execute(
            "SELECT option, value FROM botamusique WHERE section=? ORDER BY rowid DESC",
            ('netease_playlists',)).fetchall()
    finally:
        conn.close()
    playlists = []
    for playlist_id, value in rows:
        try:
            playlist = json.loads(value)
        except (TypeError, ValueError):
            log.warning("web: invalid saved Netease playlist: %s", playlist_id)
            continue
        playlists.append({
            'id': str(playlist.get('id', playlist_id)),
            'name': playlist.get('name', ''),
            'cover': playlist.get('cover'),
            'count': len(playlist.get('songs') or []),
        })
    return jsonify({'playlists': playlists})


@web.route("/netease/qr_login.png", methods=['GET'])
@requires_auth
def netease_qr_login_image():
    image_path = _get_netease_qr_image_path()
    if not os.path.isfile(image_path):
        abort(404)
    return send_file(image_path, mimetype='image/png')


@web.route("/post", methods=['POST'])
@requires_auth
def post():
    global log
    user = session.get('user', 'Remote Control')

    payload = request.get_json() if request.is_json else request.form
    if payload:
        log.debug("web: Post request from %s: %s" % (request.remote_addr, str(payload)))

        if 'add_item_at_once' in payload:
            music_wrapper = get_cached_wrapper_by_id(payload['add_item_at_once'], user)
            if music_wrapper:
                var.playlist.insert(var.playlist.current_index + 1, music_wrapper)
                log.info('web: add to playlist(next): ' + music_wrapper.format_debug_string())
                if not var.bot.is_pause:
                    var.bot.interrupt()
                else:
                    var.bot.is_pause = False
            else:
                abort(404)

        if 'add_item_bottom' in payload:
            music_wrapper = get_cached_wrapper_by_id(payload['add_item_bottom'], user)

            if music_wrapper:
                var.playlist.append(music_wrapper)
                log.info('web: add to playlist(bottom): ' + music_wrapper.format_debug_string())
            else:
                abort(404)

        elif 'add_item_next' in payload:
            music_wrapper = get_cached_wrapper_by_id(payload['add_item_next'], user)
            if music_wrapper:
                var.playlist.insert(var.playlist.current_index + 1, music_wrapper)
                log.info('web: add to playlist(next): ' + music_wrapper.format_debug_string())
            else:
                abort(404)

        elif 'move_item_next' in payload:
            try:
                index = int(payload['move_item_next'])
            except (TypeError, ValueError):
                abort(400)

            if index < 0 or index >= len(var.playlist):
                abort(400)

            current = var.playlist.current_index
            if index != current and index != current + 1:
                wrapper = var.playlist[index]
                item_obj = wrapper.item()
                target = current if index < current else current + 1
                # 鍏堜繚瀛橀噸寤轰俊鎭紙remove 浼氶噴鏀?radio 绛夐潪鎸佷箙鍖?item 鐨勭紦瀛橈級
                rebuild_kwargs = {}
                if item_obj.type == 'radio':
                    rebuild_kwargs = {'type': 'radio', 'url': item_obj.url, 'name': item_obj.title}
                elif item_obj.type == 'netease':
                    rebuild_kwargs = {
                        'type': 'netease',
                        'song_id': item_obj.song_id,
                        'title': item_obj.title,
                        'artist': item_obj.artist,
                    }
                elif item_obj.type == 'url':
                    rebuild_kwargs = {'type': 'url', 'url': item_obj.url}
                elif item_obj.type == 'file':
                    rebuild_kwargs = {'type': 'file', 'path': item_obj.path}
                else:
                    rebuild_kwargs = {'type': item_obj.type, 'url': item_obj.url}
                var.playlist.remove(index)
                # 閲嶅缓 wrapper锛堜繚鎸佸師 item 鍦ㄧ紦瀛樹腑锛岄伩鍏嶆覆鏌撴椂 ItemNotCachedError锛?
                music_wrapper = get_cached_wrapper_from_scrap(user=user, **rebuild_kwargs)
                var.playlist.insert(target, music_wrapper)
                log.info("web: move playlist item next: " + music_wrapper.format_debug_string())
                # 娉ㄦ剰锛氳繖閲屼笉鑳借皟 var.bot.interrupt()
                # interrupt() 浼氭潃鎺?ffmpeg 绾跨▼锛宭oop 妫€娴嬪埌 last_ffmpeg_err 闈炵┖鏃?
                # 浼氬垹闄ゅ綋鍓嶆挱鏀炬瓕鏇诧紙mumbleBot.py 绾?565-575 琛岋級锛屽鑷撮槦鍒椾涪姝屻€?

        elif 'add_url' in payload:
            music_wrapper = get_cached_wrapper_from_scrap(type='url', url=payload['add_url'], user=user)
            var.playlist.append(music_wrapper)

            log.info("web: add to playlist: " + music_wrapper.format_debug_string())
            if len(var.playlist) == 2:
                # If I am the second item on the playlist. (I am the next one!)
                var.bot.async_download_next()

        elif 'add_radio' in payload:
            url = payload['add_radio']
            music_wrapper = get_cached_wrapper_from_scrap(type='radio', url=url, user=user)
            var.playlist.append(music_wrapper)

            log.info("cmd: add to playlist: " + music_wrapper.format_debug_string())

        elif 'add_netease' in payload:
            song_id = payload['add_netease']
            try:
                client = NeteaseClient(var.config.get('netease', 'api_url'))
                cookie_manager = NeteaseCookieManager(
                    var.config.get('netease', 'cookie_file', fallback='config/netease_cookie.txt'))
                url = client.get_song_url(song_id, cookie_manager.get_cookie())
                detail = client.get_song_detail(song_id)
                title = (detail.get('name', '') or '') if detail else ''
                artist = (detail.get('artist', '') or '') if detail else ''
            except (requests.RequestException, ValueError, TypeError):
                log.exception("web: could not get Netease song URL")
                abort(502)
            if not url:
                abort(400)
            music_wrapper = get_cached_wrapper_from_scrap(
                type='netease',
                song_id=song_id,
                title=title,
                artist=artist,
                user=user)
            var.playlist.append(music_wrapper)
            if detail:
                _add_netease_listening_time(detail.get('duration'))
            log.info("web: add Netease item to playlist: " + music_wrapper.format_debug_string())
            if len(var.playlist) == 2:
                var.bot.async_download_next()
        elif 'add_ximalaya' in payload:
            xm_payload = payload['add_ximalaya']
            if isinstance(xm_payload, str):
                try:
                    xm_payload = json.loads(xm_payload)
                except ValueError:
                    abort(400)
            try:
                if xm_payload.get('kind') == 'album':
                    album_id = xm_payload.get('album_id', '')
                    album_title = xm_payload.get('album_title', '')
                    track_ids = xm_payload.get('track_ids') or None
                    if isinstance(track_ids, str):
                        track_ids = [track_ids]
                    wanted = set(str(t) for t in (track_ids or []))
                    page_num = 1
                    added = 0
                    while True:
                        resp = requests.get(
                            'https://www.ximalaya.com/revision/album/getTracksList',
                            params={'albumId': album_id, 'pageNum': page_num, 'sort': 0},
                            headers={**_XM_UA, 'Referer': 'https://www.ximalaya.com/album/{}'.format(album_id)},
                            timeout=30)
                        resp.raise_for_status()
                        body = resp.json()
                        data = body.get('data') or {}
                        tracks = data.get('tracks') or []
                        if not tracks:
                            break
                        for t in tracks:
                            tid = str(t.get('trackId', ''))
                            if wanted and tid not in wanted:
                                continue
                            music_wrapper = get_cached_wrapper_from_scrap(
                                type='ximalaya',
                                track_id=tid,
                                title=t.get('title', ''),
                                artist=t.get('anchorName', ''),
                                user=user)
                            var.playlist.append(music_wrapper)
                            added += 1
                        page_size = int(data.get('pageSize') or 30)
                        total = int(data.get('trackTotalCount') or 0)
                        if page_num * page_size >= total or len(tracks) < page_size:
                            break
                        page_num += 1
                    log.info("web: add Ximalaya album %s (%d tracks)", album_id, added)
                    if len(var.playlist) == 2:
                        var.bot.async_download_next()
                    return jsonify({'ok': True, 'added': added})
                else:
                    track_id = str(xm_payload.get('track_id', ''))
                    title = xm_payload.get('title', '')
                    artist = xm_payload.get('artist', '')
                    music_wrapper = get_cached_wrapper_from_scrap(
                        type='ximalaya', track_id=track_id, title=title,
                        artist=artist, user=user)
                    var.playlist.append(music_wrapper)
                    log.info("web: add Ximalaya track: " + music_wrapper.format_debug_string())
                    if len(var.playlist) == 2:
                        var.bot.async_download_next()
                    return jsonify({'ok': True, 'added': 1})
            except (requests.RequestException, ValueError, TypeError):
                log.exception("web: could not add Ximalaya item")
                abort(502)
        elif 'save_netease_playlist' in payload:
            playlist_payload = payload['save_netease_playlist']
            if isinstance(playlist_payload, str):
                try:
                    playlist_payload = json.loads(playlist_payload)
                except (TypeError, ValueError):
                    abort(400)
            if not isinstance(playlist_payload, dict):
                abort(400)
            playlist_id = _extract_netease_playlist_id(playlist_payload.get('id'))
            songs = playlist_payload.get('songs') or []
            if not playlist_id or not isinstance(songs, list):
                abort(400)
            saved_playlist = {
                'id': playlist_id,
                'name': str(playlist_payload.get('name') or ''),
                'cover': playlist_payload.get('cover'),
                'saved_at': int(time.time()),
                'songs': [
                    {
                        'id': str(song.get('id')),
                        'name': str(song.get('name') or ''),
                        'artist': str(song.get('artist') or ''),
                        'duration': song.get('duration'),
                    }
                    for song in songs
                    if isinstance(song, dict) and song.get('id') is not None
                ],
            }
            var.db.set('netease_playlists', playlist_id, json.dumps(saved_playlist, ensure_ascii=False))
            return jsonify({'ok': True})

        elif 'play_netease_playlist' in payload or 'play_netease_playlist_url' in payload:
            playlist_id = payload.get('play_netease_playlist') or payload.get('play_netease_playlist_url')
            playlist_id = _extract_netease_playlist_id(playlist_id)
            if not playlist_id:
                abort(400)
            try:
                client, cookie = _get_netease_client_and_cookie()
                if 'play_netease_playlist' in payload:
                    saved_value = var.db.get('netease_playlists', playlist_id, fallback=None)
                    if not saved_value:
                        return jsonify({'error': tr_web('netease_playlist_no_result')}), 404
                    saved_playlist = json.loads(saved_value)
                    tracks = saved_playlist.get('songs') or []
                else:
                    tracks = client.get_playlist_tracks(playlist_id)
                var.playlist.clear()
                added, skipped = _add_netease_tracks(client, cookie, tracks, user)
            except (requests.RequestException, ValueError, TypeError):
                log.exception("web: Netease playlist playback failed")
                return jsonify({'error': tr_web('netease_playlist_error')}), 502
            return jsonify({'added': added, 'skipped': skipped})

        elif 'delete_netease_playlist' in payload:
            playlist_id = _extract_netease_playlist_id(payload['delete_netease_playlist'])
            if not playlist_id:
                abort(400)
            var.db.remove_option('netease_playlists', playlist_id)
            return jsonify({'ok': True})

        elif 'delete_music' in payload:
            music_wrapper = var.playlist[int(payload['delete_music'])]
            log.info("web: delete from playlist: " + music_wrapper.format_debug_string())

            if len(var.playlist) >= int(payload['delete_music']):
                index = int(payload['delete_music'])

                if index == var.playlist.current_index:
                    var.playlist.remove(index)

                    if index < len(var.playlist):
                        if not var.bot.is_pause:
                            var.bot.interrupt()
                            var.playlist.current_index -= 1
                            # then the bot will move to next item

                    else:  # if item deleted is the last item of the queue
                        var.playlist.current_index -= 1
                        if not var.bot.is_pause:
                            var.bot.interrupt()
                else:
                    var.playlist.remove(index)

        elif 'play_music' in payload:
            music_wrapper = var.playlist[int(payload['play_music'])]
            log.info("web: jump to: " + music_wrapper.format_debug_string())

            if len(var.playlist) >= int(payload['play_music']):
                var.bot.play(int(payload['play_music']))
                time.sleep(0.1)
        elif 'move_playhead' in payload:
            if float(payload['move_playhead']) < var.playlist.current_item().item().duration:
                log.info(f"web: move playhead to {float(payload['move_playhead'])} s.")
                var.bot.play(var.playlist.current_index, float(payload['move_playhead']))

        elif 'delete_item_from_library' in payload:
            _id = payload['delete_item_from_library']
            var.playlist.remove_by_id(_id)
            item = var.cache.get_item_by_id(_id)

            if os.path.isfile(item.uri()):
                log.info("web: delete file " + item.uri())
                os.remove(item.uri())

            var.cache.free_and_delete(_id)
            time.sleep(0.1)

        elif 'add_tag' in payload:
            music_wrappers = get_cached_wrappers_by_tags([payload['add_tag']], user)
            for music_wrapper in music_wrappers:
                log.info("cmd: add to playlist: " + music_wrapper.format_debug_string())
            var.playlist.extend(music_wrappers)

        elif 'action' in payload:
            action = payload['action']
            if action == "random":
                if var.playlist.mode != "random":
                    var.playlist = media.playlist.get_playlist("random", var.playlist)
                else:
                    var.playlist.randomize()
                var.bot.interrupt()
                var.db.set('playlist', 'playback_mode', "random")
                log.info("web: playback mode changed to random.")
            if action == "one-shot":
                var.playlist = media.playlist.get_playlist("one-shot", var.playlist)
                var.db.set('playlist', 'playback_mode', "one-shot")
                log.info("web: playback mode changed to one-shot.")
            if action == "repeat":
                var.playlist = media.playlist.get_playlist("repeat", var.playlist)
                var.db.set('playlist', 'playback_mode', "repeat")
                log.info("web: playback mode changed to repeat.")
            if action == "autoplay":
                var.playlist = media.playlist.get_playlist("autoplay", var.playlist)
                var.db.set('playlist', 'playback_mode', "autoplay")
                log.info("web: playback mode changed to autoplay.")
            if action == "rescan":
                var.cache.build_dir_cache()
                var.music_db.manage_special_tags()
                log.info("web: Local file cache refreshed.")
            elif action == "stop":
                if var.config.getboolean("bot", "clear_when_stop_in_oneshot") \
                        and var.playlist.mode == 'one-shot':
                    var.bot.clear()
                else:
                    var.bot.stop()
            elif action == "next":
                if not var.bot.is_pause:
                    var.bot.interrupt()
                else:
                    var.playlist.next()
                    var.bot.wait_for_ready = True
            elif action == "pause":
                var.bot.pause()
            elif action == "resume":
                var.bot.resume()
            elif action == "clear":
                var.bot.clear()
            elif action == "volume_up":
                if var.bot.volume_helper.plain_volume_set + 0.03 < 1.0:
                    var.bot.volume_helper.set_volume(var.bot.volume_helper.plain_volume_set + 0.03)
                else:
                    var.bot.volume_helper.set_volume(1.0)
                var.db.set('bot', 'volume', str(var.bot.volume_helper.plain_volume_set))
                log.info("web: volume up to %d" % (var.bot.volume_helper.plain_volume_set * 100))
            elif action == "volume_down":
                if var.bot.volume_helper.plain_volume_set - 0.03 > 0:
                    var.bot.volume_helper.set_volume(var.bot.unconverted_volume - 0.03)
                else:
                    var.bot.volume_helper.set_volume(1.0)
                var.db.set('bot', 'volume', str(var.bot.volume_helper.plain_volume_set))
                log.info("web: volume down to %d" % (var.bot.volume_helper.plain_volume_set * 100))
            elif action == "volume_set_value":
                if 'new_volume' in payload:
                    if float(payload['new_volume']) > 1:
                        var.bot.volume_helper.set_volume(1.0)
                    elif float(payload['new_volume']) < 0:
                        var.bot.volume_helper.set_volume(0)
                    else:
                        # value for new volume is between 0 and 1, round to two decimal digits
                        var.bot.volume_helper.set_volume(round(float(payload['new_volume']), 2))

                    var.db.set('bot', 'volume', str(var.bot.volume_helper.plain_volume_set))
                    log.info("web: volume set to %d" % (var.bot.volume_helper.plain_volume_set * 100))

    return status()


def build_library_query_condition(form):
    try:
        condition = Condition()

        types = form['type'].split(",")
        sub_cond = Condition()
        for type in types:
            sub_cond.or_equal("type", type)
        condition.and_sub_condition(sub_cond)

        if form['type'] == 'file':
            folder = form['dir']
            if folder == ".":
                folder = ""
            if not folder.endswith('/') and folder:
                folder += '/'
            condition.and_like('path', folder + '%')

        tags = form['tags'].split(",")
        for tag in tags:
            if tag:
                condition.and_like("tags", f"%{tag},%", case_sensitive=False)

        _keywords = form['keywords'].split(" ")
        keywords = []
        for kw in _keywords:
            if kw:
                keywords.append(kw)

        for keyword in keywords:
            condition.and_like("keywords", f"%{keyword}%", case_sensitive=False)

        condition.order_by('create_at', desc=True)

        return condition
    except KeyError:
        abort(400)


@web.route("/library/info", methods=['GET'])
@requires_auth
def library_info():
    global log

    while var.cache.dir_lock.locked():
        time.sleep(0.1)

    tags = var.music_db.query_all_tags()
    max_upload_file_size = util.parse_file_size(var.config.get("webinterface", "max_upload_file_size"))

    return jsonify(dict(
        dirs=get_all_dirs(),
        upload_enabled=var.config.getboolean("webinterface", "upload_enabled") or var.bot.is_admin(user),
        delete_allowed=var.config.getboolean("bot", "delete_allowed") or var.bot.is_admin(user),
        tags=tags,
        max_upload_file_size=max_upload_file_size
    ))


@web.route("/library", methods=['POST'])
@requires_auth
def library():
    global log
    ITEM_PER_PAGE = 10

    payload = request.form if request.form else request.json
    if payload:
        log.debug("web: Post request from %s: %s" % (request.remote_addr, str(payload)))

        if payload['action'] in ['add', 'query', 'delete']:
            condition = build_library_query_condition(payload)

            total_count = 0
            try:
                total_count = var.music_db.query_music_count(condition)
            except sqlite3.OperationalError:
                pass

            if not total_count:
                return jsonify({
                    'items': [],
                    'total_pages': 0,
                    'active_page': 0
                })

            if payload['action'] == 'add':
                items = dicts_to_items(var.music_db.query_music(condition))
                music_wrappers = []
                for item in items:
                    music_wrapper = get_cached_wrapper(item, user)
                    music_wrappers.append(music_wrapper)

                    log.info("cmd: add to playlist: " + music_wrapper.format_debug_string())

                var.playlist.extend(music_wrappers)

                return redirect("./", code=302)
            elif payload['action'] == 'delete':
                if var.config.getboolean("bot", "delete_allowed"):
                    items = dicts_to_items(var.music_db.query_music(condition))
                    for item in items:
                        var.playlist.remove_by_id(item.id)
                        item = var.cache.get_item_by_id(item.id)

                        if os.path.isfile(item.uri()):
                            log.info("web: delete file " + item.uri())
                            os.remove(item.uri())

                        var.cache.free_and_delete(item.id)

                    if len(os.listdir(var.music_folder + payload['dir'])) == 0:
                        os.rmdir(var.music_folder + payload['dir'])

                    time.sleep(0.1)
                    return redirect("./", code=302)
                else:
                    abort(403)
            else:
                page_count = math.ceil(total_count / ITEM_PER_PAGE)

                current_page = int(payload['page']) if 'page' in payload else 1
                if current_page <= page_count:
                    condition.offset((current_page - 1) * ITEM_PER_PAGE)
                else:
                    current_page = 1

                condition.limit(ITEM_PER_PAGE)
                items = dicts_to_items(var.music_db.query_music(condition))

                results = []
                for item in items:
                    result = {'id': item.id, 'title': item.title, 'type': item.display_type(),
                              'tags': [(tag, tag_color(tag)) for tag in item.tags]}
                    if item.type != 'radio' and item.thumbnail:
                        result['thumb'] = f"data:image/PNG;base64,{item.thumbnail}"
                    else:
                        result['thumb'] = "static/image/unknown-album.png"

                    if item.type in ('file', 'netease'):
                        result['path'] = item.path
                        result['artist'] = item.artist
                    else:
                        result['path'] = item.url
                        result['artist'] = "??"

                    results.append(result)

                return jsonify({
                    'items': results,
                    'total_pages': page_count,
                    'active_page': current_page
                })
        elif payload['action'] == 'edit_tags':
            tags = list(dict.fromkeys(payload['tags'].split(",")))  # remove duplicated items
            if payload['id'] in var.cache:
                music_wrapper = get_cached_wrapper_by_id(payload['id'], user)
                music_wrapper.clear_tags()
                music_wrapper.add_tags(tags)
                var.playlist.version += 1
            else:
                item = var.music_db.query_music_by_id(payload['id'])
                item['tags'] = tags
                var.music_db.insert_music(item)
            return redirect("./", code=302)

    else:
        abort(400)


@web.route('/upload', methods=["POST"])
@requires_auth
def upload():
    global log

    if not var.config.getboolean("webinterface", "upload_enabled"):
        abort(403)

    file = request.files['file']
    if not file:
        abort(400)

    filename = file.filename
    if filename == '':
        abort(400)

    targetdir = request.form['targetdir'].strip()
    if targetdir == '':
        targetdir = 'uploads/'
    elif '../' in targetdir:
        abort(403)

    log.info('web: Uploading file from %s:' % request.remote_addr)
    log.info('web: - filename: ' + filename)
    log.info('web: - targetdir: ' + targetdir)
    log.info('web: - mimetype: ' + file.mimetype)

    if "audio" in file.mimetype or "video" in file.mimetype:
        storagepath = os.path.abspath(os.path.join(var.music_folder, targetdir))
        if not storagepath.startswith(os.path.abspath(var.music_folder)):
            abort(403)

        try:
            os.makedirs(storagepath)
        except OSError as ee:
            if ee.errno != errno.EEXIST:
                log.error(f'web: failed to create directory {storagepath}')
                abort(500)

        filepath = os.path.join(storagepath, filename)
        log.info('web: - file saved at: ' + filepath)
        if os.path.exists(filepath):
            return 'File existed!', 409

        file.save(filepath)
    else:
        log.error(f'web: unsupported file type {file.mimetype}! File was not saved.')
        return 'Unsupported media type!', 415

    return '', 200


@web.route('/download', methods=["GET"])
@requires_auth
def download():
    global log

    if 'id' in request.args and request.args['id']:
        item = dicts_to_items(var.music_db.query_music(
            Condition().and_equal('id', request.args['id'])))[0]

        requested_file = item.uri()
        log.info('web: Download of file %s requested from %s:' % (requested_file, request.remote_addr))

        try:
            return send_file(requested_file, as_attachment=True)
        except Exception as e:
            log.exception(e)
            abort(404)

    else:
        condition = build_library_query_condition(request.args)
        items = dicts_to_items(var.music_db.query_music(condition))

        zipfile = util.zipdir([item.uri() for item in items])

        try:
            return send_file(zipfile, as_attachment=True)
        except Exception as e:
            log.exception(e)
            abort(404)

    return abort(400)


if __name__ == '__main__':
    web.run(port=8181, host="127.0.0.1")
