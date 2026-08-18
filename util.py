#!/usr/bin/python3
# coding=utf-8

import hashlib
import hmac
import html
import magic
import os
import io
import sys
import threading
import variables as var
import zipfile
import re
import subprocess as sp
import logging
from importlib import reload
from sys import platform
import traceback
import requests
from packaging import version

import yt_dlp as youtube_dl
YT_PKG_NAME = 'yt-dlp'

log = logging.getLogger("bot")


def solve_filepath(path):
    if not path:
        return ''

    if path[0] == '/':
        return path
    elif os.path.exists(path):
        return path
    else:
        mydir = os.path.dirname(os.path.realpath(__file__))
        return mydir + '/' + path


def get_recursive_file_list_sorted(path):
    filelist = []
    for root, dirs, files in os.walk(path, topdown=True, onerror=None, followlinks=True):
        relroot = root.replace(path, '', 1)
        if relroot != '' and relroot in var.config.get('bot', 'ignored_folders'):
            continue
        for file in files:
            if file in var.config.get('bot', 'ignored_files'):
                continue

            fullpath = os.path.join(path, relroot, file)
            if not os.access(fullpath, os.R_OK):
                continue

            try:
                mime = magic.from_file(fullpath, mime=True)
                if 'audio' in mime or 'audio' in magic.from_file(fullpath).lower() or 'video' in mime:
                    filelist.append(os.path.join(relroot, file))
            except:
                pass

    filelist.sort()
    return filelist


# - zips files
# - returns the absolute path of the created zip file
# - zip file will be in the applications tmp folder (according to configuration)
# - format of the filename itself = prefix_hash.zip
#       - prefix can be controlled by the caller
#       - hash is a sha1 of the string representation of the directories' contents (which are
#           zipped)
def zipdir(files, zipname_prefix=None):
    zipname = var.tmp_folder
    if zipname_prefix and '../' not in zipname_prefix:
        zipname += zipname_prefix.strip().replace('/', '_') + '_'

    _hash = hashlib.sha1(str(files).encode()).hexdigest()
    zipname += _hash + '.zip'

    if os.path.exists(zipname):
        return zipname

    zipf = zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED)

    for file_to_add in files:
        if not os.access(file_to_add, os.R_OK):
            continue
        if file_to_add in var.config.get('bot', 'ignored_files'):
            continue

        add_file_as = os.path.basename(file_to_add)
        zipf.write(file_to_add, add_file_as)

    zipf.close()
    return zipname


def get_user_ban():
    res = "List of ban hash"
    for i in var.db.items("user_ban"):
        res += "<br/>" + i[0]
    return res


def new_release_version(target):
    if target == "testing":
        r = requests.get("https://packages.azlux.fr/botamusique/testing-version")
    else:
        r = requests.get("https://packages.azlux.fr/botamusique/version")
    v = r.text
    return v.rstrip()


def fetch_changelog():
    r = requests.get("https://packages.azlux.fr/botamusique/changelog")
    c = r.text
    return c


def check_update(current_version):
    global log
    log.debug("update: checking for updates...")
    new_version = new_release_version(var.config.get('bot', 'target_version'))
    if version.parse(new_version) > version.parse(current_version):
        changelog = fetch_changelog()
        log.info(f"update: new version {new_version} found, current installed version {current_version}.")
        log.info(f"update: changelog: {changelog}")
        changelog = changelog.replace("\n", "<br>")
        return new_version, changelog
    else:
        log.debug("update: no new version found.")
        return None, None


def update(current_version):
    global log

    target = var.config.get('bot', 'target_version')
    new_version = new_release_version(target)
    msg = ""
    if target == "git":
        msg = "git install, I do nothing<br/>"

    elif (target == "stable" and version.parse(new_version) > version.parse(current_version)) or \
            (target == "testing" and version.parse(new_version) != version.parse(current_version)):
        log.info('update: new version, start updating...')
        tp = sp.check_output(['/usr/bin/env', 'bash', 'update.sh', target]).decode()
        log.debug(tp)
        log.info('update: update pip libraries dependencies')
        sp.check_output([var.config.get('bot', 'pip3_path'), 'install', '--upgrade', '-r', 'requirements.txt']).decode()
        msg = "New version installed, please restart the bot.<br/>"

    log.info(f'update: starting update {YT_PKG_NAME} via pip3')
    tp = sp.check_output([var.config.get('bot', 'pip3_path'), 'install', '--upgrade', YT_PKG_NAME]).decode()
    if f"Collecting {YT_PKG_NAME}" in tp.splitlines():
        msg += "Update done: " + tp.split('Successfully installed')[1]
    else:
        msg += YT_PKG_NAME.capitalize() + " is up-to-date"

    reload(youtube_dl)
    msg += "<br/>" + YT_PKG_NAME.capitalize() + " reloaded"
    return msg


def pipe_no_wait():
    """ Generate a non-block pipe used to fetch the STDERR of ffmpeg.
    """

    if platform == "linux" or platform == "linux2" or platform == "darwin" or platform.startswith("openbsd") or platform.startswith("freebsd"):
        import fcntl
        import os

        pipe_rd = 0
        pipe_wd = 0

        if hasattr(os, "pipe2"):
            pipe_rd, pipe_wd = os.pipe2(os.O_NONBLOCK)
        else:
            pipe_rd, pipe_wd = os.pipe()

            try:
                fl = fcntl.fcntl(pipe_rd, fcntl.F_GETFL)
                fcntl.fcntl(pipe_rd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            except:
                print(sys.exc_info()[1])
                return None, None
        return pipe_rd, pipe_wd

    elif platform == "win32":
        # https://stackoverflow.com/questions/34504970/non-blocking-read-on-os-pipe-on-windows
        import msvcrt
        import os

        from ctypes import windll, byref, wintypes, WinError, POINTER
        from ctypes.wintypes import HANDLE, DWORD, BOOL

        pipe_rd, pipe_wd = os.pipe()

        LPDWORD = POINTER(DWORD)
        PIPE_NOWAIT = wintypes.DWORD(0x00000001)
        ERROR_NO_DATA = 232

        SetNamedPipeHandleState = windll.kernel32.SetNamedPipeHandleState
        SetNamedPipeHandleState.argtypes = [HANDLE, LPDWORD, LPDWORD, LPDWORD]
        SetNamedPipeHandleState.restype = BOOL

        h = msvcrt.get_osfhandle(pipe_rd)

        res = windll.kernel32.SetNamedPipeHandleState(h, byref(PIPE_NOWAIT), None, None)
        if res == 0:
            print(WinError())
            return None, None
        return pipe_rd, pipe_wd


class Dir(object):
    def __init__(self, path):
        self.name = os.path.basename(path.strip('/'))
        self.fullpath = path
        self.subdirs = {}
        self.files = []

    def add_file(self, file):
        if file.startswith(self.name + '/'):
            file = file.replace(self.name + '/', '', 1)

        if '/' in file:
            # This file is in a subdir
            subdir = file.split('/')[0]
            if subdir in self.subdirs:
                self.subdirs[subdir].add_file(file)
            else:
                self.subdirs[subdir] = Dir(os.path.join(self.fullpath, subdir))
                self.subdirs[subdir].add_file(file)
        else:
            self.files.append(file)
        return True

    def get_subdirs(self, path=None):
        subdirs = []
        if path and path != '' and path != './':
            subdir = path.split('/')[0]
            if subdir in self.subdirs:
                searchpath = '/'.join(path.split('/')[1::])
                subdirs = self.subdirs[subdir].get_subdirs(searchpath)
                subdirs = list(map(lambda subsubdir: os.path.join(subdir, subsubdir), subdirs))
        else:
            subdirs = self.subdirs

        return subdirs

    def get_subdirs_recursively(self, path=None):
        subdirs = []
        if path and path != '' and path != './':
            subdir = path.split('/')[0]
            if subdir in self.subdirs:
                searchpath = '/'.join(path.split('/')[1::])
                subdirs = self.subdirs[subdir].get_subdirs_recursively(searchpath)
        else:
            subdirs = list(self.subdirs.keys())

            for key, val in self.subdirs.items():
                subdirs.extend(map(lambda subdir: key + '/' + subdir, val.get_subdirs_recursively()))

        subdirs.sort()
        return subdirs

    def get_files(self, path=None):
        files = []
        if path and path != '' and path != './':
            subdir = path.split('/')[0]
            if subdir in self.subdirs:
                searchpath = '/'.join(path.split('/')[1::])
                files = self.subdirs[subdir].get_files(searchpath)
        else:
            files = self.files

        return files

    def get_files_recursively(self, path=None):
        files = []
        if path and path != '' and path != './':
            subdir = path.split('/')[0]
            if subdir in self.subdirs:
                searchpath = '/'.join(path.split('/')[1::])
                files = self.subdirs[subdir].get_files_recursively(searchpath)
        else:
            files = self.files

            for key, val in self.subdirs.items():
                files.extend(map(lambda file: key + '/' + file, val.get_files_recursively()))

        return files

    def render_text(self, ident=0):
        print('{}{}/'.format(' ' * (ident * 4), self.name))
        for key, val in self.subdirs.items():
            val.render_text(ident + 1)
        for file in self.files:
            print('{}{}'.format(' ' * (ident + 1) * 4, file))


# Parse the html from the message to get the URL

def get_url_from_input(string):
    string = string.strip()
    if not (string.startswith("http") or string.startswith("HTTP")):
        res = re.search('href="(.+?)"', string, flags=re.IGNORECASE)
        if res:
            string = res.group(1)
        else:
            return ""

    match = re.search("(http|https)://(\S*)?/(\S*)", string, flags=re.IGNORECASE)
    if match:
        url = match[1].lower() + "://" + match[2].lower() + "/" + match[3]
        # https://github.com/mumble-voip/mumble/issues/4999
        return html.unescape(url)
    else:
        return ""


def youtube_search(query):
    global log
    import json

    try:
        cookie_file =  var.config.get('youtube_dl', 'cookie_file')
        cookie = parse_cookie_file(cookie_file) if cookie_file else {}
        r = requests.get("https://www.youtube.com/results", cookies=cookie,
                         params={'search_query': query}, timeout=5)
        result_json_match = re.findall(r">var ytInitialData = (.*?);</script>", r.text)

        if not len(result_json_match):
            log.error("util: can not interpret youtube search web page")
            return False

        result_big_json = json.loads(result_json_match[0])
        results = []
        try:
            for item in result_big_json['contents']['twoColumnSearchResultsRenderer']\
                    ['primaryContents']['sectionListRenderer']['contents'][0]\
                    ['itemSectionRenderer']['contents']:
                if 'videoRenderer' not in item:
                    continue
                video_info = item['videoRenderer']
                title = video_info['title']['runs'][0]['text']
                video_id = video_info['videoId']
                uploader = video_info['ownerText']['runs'][0]['text']
                results.append([video_id, title, uploader])
        except (json.JSONDecodeError, KeyError):
            log.error("util: can not interpret youtube search web page")
            return False

        return results

    except (requests.exceptions.ConnectionError, requests.exceptions.HTTPError, requests.exceptions.Timeout):
        error_traceback = traceback.format_exc().split("During")[0]
        log.error("util: youtube query failed with error:\n %s" % error_traceback)
        return False


def get_media_duration(path):
    command = ("ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", path)
    process = sp.Popen(command, stdout=sp.PIPE, stderr=sp.PIPE)
    stdout, stderr = process.communicate()

    try:
        if not stderr:
            return float(stdout)
        else:
            return 0
    except ValueError:
        return 0


def parse_time(human):
    match = re.search("(?:(\d\d):)?(?:(\d\d):)?(\d+(?:\.\d*)?)", human, flags=re.IGNORECASE)
    if match:
        if match[1] is None and match[2] is None:
            return float(match[3])
        elif match[2] is None:
            return float(match[3]) + 60 * int(match[1])
        else:
            return float(match[3]) + 60 * int(match[2]) + 3600 * int(match[1])
    else:
        raise ValueError("Invalid time string given.")


def format_time(seconds):
    hours = seconds // 3600
    seconds = seconds % 3600
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{hours:d}:{minutes:02d}:{seconds:02d}"


def parse_file_size(human):
    units = {"B": 1, "KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024, "TB": 1024 * 1024 * 1024 * 1024,
             "K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024, "T": 1024 * 1024 * 1024 * 1024}
    match = re.search("(\d+(?:\.\d*)?)\s*([A-Za-z]+)", human, flags=re.IGNORECASE)
    if match:
        num = float(match[1])
        unit = match[2].upper()
        if unit in units:
            return int(num * units[unit])

    raise ValueError("Invalid file size given.")


def get_salted_password_hash(password):
    salt = os.urandom(10)
    hashed = hashlib.pbkdf2_hmac('sha1', password.encode("utf-8"), salt, 100000)

    return hashed.hex(), salt.hex()


def verify_password(password, salted_hash, salt):
    hashed = hashlib.pbkdf2_hmac('sha1', password.encode("utf-8"), bytearray.fromhex(salt), 100000)
    return hmac.compare_digest(hashed.hex(), salted_hash)


def get_supported_language():
    root_dir = os.path.dirname(__file__)
    lang_files = os.listdir(os.path.join(root_dir, 'lang'))
    lang_list = []
    for lang_file in lang_files:
        match = re.search("([a-z]{2}_[A-Z]{2})\.json", lang_file)
        if match:
            lang_list.append(match[1])

    return lang_list


def set_logging_formatter(handler: logging.Handler, logging_level):
    if logging_level == logging.DEBUG:
        formatter = logging.Formatter(
            "[%(asctime)s] > [%(threadName)s] > "
            "[%(filename)s:%(lineno)d] %(message)s"
        )
    else:
        formatter = logging.Formatter(
            '[%(asctime)s %(levelname)s] %(message)s', "%b %d %H:%M:%S")

    handler.setFormatter(formatter)


def get_snapshot_version():
    import subprocess
    wd = os.getcwd()
    root_dir = os.path.dirname(__file__)
    os.chdir(root_dir)

    ver = "unknown"
    if os.path.exists(os.path.join(root_dir, ".git")):
        try:
            ret = subprocess.check_output(["git", "describe", "--tags"]).strip()
            ver = ret.decode("utf-8")
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                with open(os.path.join(root_dir, ".git/refs/heads/master")) as f:
                    ver = "g" + f.read()[:7]
            except FileNotFoundError:
                pass

    os.chdir(wd)
    return ver


class LoggerIOWrapper(io.TextIOWrapper):
    def __init__(self, logger: logging.Logger, logging_level, fallback_io_buffer):
        super().__init__(fallback_io_buffer, write_through=True)
        self.logger = logger
        self.logging_level = logging_level

    def write(self, text):
        if isinstance(text, bytes):
            msg = text.decode('utf-8').rstrip()
            self.logger.log(self.logging_level, msg)
            super().write(msg + "\n")
        else:
            self.logger.log(self.logging_level, text.rstrip())
            super().write(text + "\n")


class VolumeHelper:
    def __init__(self, plain_volume=0, ducking_plain_volume=0):
        self.plain_volume_set = 0
        self.plain_ducking_volume_set = 0
        self.volume_set = 0
        self.ducking_volume_set = 0

        self.real_volume = 0

        self.set_volume(plain_volume)
        self.set_ducking_volume(ducking_plain_volume)

    def set_volume(self, plain_volume):
        self.volume_set = self._convert_volume(plain_volume)
        self.plain_volume_set = plain_volume

    def set_ducking_volume(self, plain_volume):
        self.ducking_volume_set = self._convert_volume(plain_volume)
        self.plain_ducking_volume_set = plain_volume

    def _convert_volume(self, volume):
        if volume == 0:
            return 0

        # convert input of 0~1 into -35~5 dB
        dB = -35 + volume * 40

        # Some dirty trick to stretch the function, to make to be 0 when input is -35 dB
        return (10 ** (dB / 20) - 10 ** (-35 / 20)) / (1 - 10 ** (-35 / 20))


_TMP_FOLDER_SIZE_UNIT = 1024 * 1024
_TMP_FOLDER_LOCKS = {}
_TMP_FOLDER_LOCKS_LOCK = threading.Lock()


class TmpFolderLimitError(Exception):
    """Raised when a download cannot fit within tmp_folder_max_size."""


def _tmp_folder_lock(path):
    lock_path = os.path.realpath(os.path.abspath(path or '.'))
    with _TMP_FOLDER_LOCKS_LOCK:
        lock = _TMP_FOLDER_LOCKS.get(lock_path)
        if lock is None:
            lock = threading.RLock()
            _TMP_FOLDER_LOCKS[lock_path] = lock
        return lock


def _normalise_paths(paths):
    return {
        os.path.realpath(os.path.abspath(path))
        for path in (paths or ())
        if path
    }


def _iter_folder_files(path):
    for root, dirs, files in os.walk(path):
        for filename in files:
            fullpath = os.path.join(root, filename)
            try:
                stat = os.stat(fullpath)
            except (FileNotFoundError, OSError):
                continue
            yield fullpath, stat.st_size, stat.st_mtime


def get_size_folder_bytes(path):
    return sum(size for _, size, _ in _iter_folder_files(path))


def get_size_folder(path):
    return int(get_size_folder_bytes(path) / _TMP_FOLDER_SIZE_UNIT)


def _is_protected(path, protected_paths):
    return os.path.realpath(os.path.abspath(path)) in protected_paths


def _remove_oldest_files(path, bytes_to_free, protected_paths=()):
    if bytes_to_free <= 0:
        return

    candidates = [
        (mtime, filename, file_size)
        for filename, file_size, mtime in _iter_folder_files(path)
        if not _is_protected(filename, protected_paths)
    ]
    candidates.sort(key=lambda item: item[0])

    freed = 0
    for _, filename, file_size in candidates:
        try:
            os.remove(filename)
            freed += file_size
            log.debug("Removing %s", filename)
        except (FileNotFoundError, OSError) as error:
            log.warning("Could not remove tmp file %s: %s", filename, error)
        if freed >= bytes_to_free:
            return


def _clear_tmp_folder(path, size, protected_paths=()):
    if size == -1:
        return

    protected_paths = _normalise_paths(protected_paths)
    if size == 0:
        for filename, _, _ in list(_iter_folder_files(path)):
            if _is_protected(filename, protected_paths):
                continue
            try:
                os.remove(filename)
            except (FileNotFoundError, OSError) as error:
                log.warning("Could not remove tmp file %s: %s", filename, error)
        return

    limit = size * _TMP_FOLDER_SIZE_UNIT
    current = get_size_folder_bytes(path)
    _remove_oldest_files(
        path,
        current - limit,
        protected_paths,
    )


def clear_tmp_folder(path, size):
    """Remove old files until tmp_folder is at most ``size`` MB.

    ``-1`` keeps the existing unlimited-cache behavior and ``0`` clears all
    files, subject to the operating system allowing the removals.
    """
    with _tmp_folder_lock(path):
        _clear_tmp_folder(path, size)


class TmpFolderQuota:
    """Serialize downloads and enforce a byte-accurate folder quota."""

    def __init__(self, path, size, protected_paths=()):
        self.path = path
        self.size = size
        self._protected_paths = _normalise_paths(protected_paths)
        self._lock = _tmp_folder_lock(path)
        self._entered = False

    def protect(self, path):
        if path:
            self._protected_paths.add(
                os.path.realpath(os.path.abspath(path)))

    def __enter__(self):
        self._lock.acquire()
        self._entered = True
        try:
            self.ensure_capacity(0)
        except Exception:
            self._entered = False
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self._entered:
            self._entered = False
            self._lock.release()
        return False

    def ensure_capacity(self, additional_bytes=0):
        """Ensure ``additional_bytes`` can be written without exceeding quota."""
        if self.size == -1:
            return
        if additional_bytes < 0:
            raise ValueError("additional_bytes must not be negative")

        limit = self.size * _TMP_FOLDER_SIZE_UNIT
        if additional_bytes > limit:
            raise TmpFolderLimitError(
                "download is larger than tmp_folder_max_size")

        current = get_size_folder_bytes(self.path)
        required = current + additional_bytes
        if required > limit:
            _remove_oldest_files(
                self.path,
                required - limit,
                self._protected_paths,
            )
            current = get_size_folder_bytes(self.path)

        if current + additional_bytes > limit:
            raise TmpFolderLimitError(
                "tmp_folder has no room for the download")


def tmp_folder_quota(path, size, protected_paths=()):
    return TmpFolderQuota(path, size, protected_paths)

def check_extra_config(config, template):
    extra = []

    for key in config.sections():
        if key in ['radio']:
            continue
        for opt in config.options(key):
            if not template.has_option(key, opt):
                extra.append((key, opt))

    return extra


def parse_cookie_file(cookiefile):
    # https://stackoverflow.com/a/54659484/1584825

    cookies = {}
    with open (cookiefile, 'r') as fp:
        for line in fp:
            if not re.match(r'^#', line):
                lineFields = line.strip().split('\t')
                cookies[lineFields[5]] = lineFields[6]
    return cookies
