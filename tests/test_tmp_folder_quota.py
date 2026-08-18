import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock


# The repository's runtime dependencies are not installed in the minimal test
# environment, but util.py only needs these modules for unrelated helpers.
if 'magic' not in sys.modules:
    magic = types.ModuleType('magic')
    magic.from_file = lambda *args, **kwargs: ''
    sys.modules['magic'] = magic
if 'yt_dlp' not in sys.modules:
    sys.modules['yt_dlp'] = types.ModuleType('yt_dlp')

import util


MB = 1024 * 1024


class TmpFolderQuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_file(self, name, size):
        path = self.folder / name
        with path.open('wb') as file:
            file.truncate(size)
        return path

    def test_clear_tmp_folder_counts_partial_files_exactly(self):
        self.write_file('old.mp3', MB)
        self.write_file('new.mp3.part', 1)

        util.clear_tmp_folder(str(self.folder), 1)

        self.assertLessEqual(util.get_size_folder_bytes(str(self.folder)), MB)

    def test_single_file_larger_than_limit_is_rejected_before_write(self):
        with self.assertRaises(util.TmpFolderLimitError):
            with util.tmp_folder_quota(str(self.folder), 1) as quota:
                quota.ensure_capacity(MB + 1)

        self.assertEqual(util.get_size_folder_bytes(str(self.folder)), 0)

    def test_concurrent_downloads_are_serialized_and_stay_within_limit(self):
        barrier = threading.Barrier(2)
        errors = []

        def download(name):
            try:
                barrier.wait()
                with util.tmp_folder_quota(
                        str(self.folder), 1,
                        protected_paths=(str(self.folder / name),)) as quota:
                    quota.ensure_capacity(MB)
                    self.write_file(name, MB)
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        threads = [
            threading.Thread(target=download, args=(name,))
            for name in ('one.mp3', 'two.mp3')
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        self.assertLessEqual(util.get_size_folder_bytes(str(self.folder)), MB)

    def test_delete_failure_does_not_allow_download_to_start(self):
        self.write_file('old.mp3', MB + 1)

        with mock.patch.object(util.os, 'remove', side_effect=OSError('busy')):
            with self.assertRaises(util.TmpFolderLimitError):
                with util.tmp_folder_quota(str(self.folder), 1):
                    pass

    def test_unlimited_size_keeps_existing_files(self):
        path = self.write_file('cached.mp3', 2 * MB)

        with util.tmp_folder_quota(str(self.folder), -1) as quota:
            quota.ensure_capacity(100 * MB)

        self.assertTrue(path.exists())
        self.assertEqual(util.get_size_folder_bytes(str(self.folder)), 2 * MB)

    def test_zero_size_clears_existing_files(self):
        self.write_file('cached.mp3', 1)

        util.clear_tmp_folder(str(self.folder), 0)

        self.assertEqual(util.get_size_folder_bytes(str(self.folder)), 0)


if __name__ == '__main__':
    unittest.main()
