"""Source-read identity regressions; synthetic metadata is not native isolation proof."""
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from test_mss_scope import scope


def metadata(**changes):
    values = dict(st_dev=11, st_ino=12, st_mode=stat.S_IFREG | 0o600,
                  st_nlink=1, st_size=2, st_mtime_ns=(1 << 60) + 13,
                  st_ctime_ns=(1 << 60) + 14, st_birthtime_ns=(1 << 60) + 7,
                  st_file_attributes=0)
    values.update(changes)
    return SimpleNamespace(**values)


class WindowsIdentityTests(unittest.TestCase):
    def observed_read(self, *, before=None, opened=None, after_fd=None, after_path=None):
        """Exercise the public bounded read with real bytes and fixed stat observations.

        Only this file's metadata observations are controlled. All ancestor path
        checks and the real open/read/close remain enabled; no authorizer or
        platform value is patched. Existing real link tests remain unchanged.
        """
        before = before or metadata()
        opened = opened or before
        after_fd = after_fd or opened
        after_path = after_path or before
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_bytes(b'{}')
            original_stat = Path.stat
            original_lstat = Path.lstat
            link_observations = 0

            def observed_stat(candidate, *args, **kwargs):
                if candidate != path:
                    return original_stat(candidate, *args, **kwargs)
                return before

            def observed_lstat(candidate, *args, **kwargs):
                nonlocal link_observations
                if candidate != path:
                    return original_lstat(candidate, *args, **kwargs)
                link_observations += 1
                return before if link_observations == 1 else after_path

            with mock.patch.object(Path, 'stat', new=observed_stat), \
                    mock.patch.object(Path, 'lstat', new=observed_lstat), \
                    mock.patch.object(scope.os, 'fstat', side_effect=[opened, after_fd]):
                return scope.read_regular(path)

    def test_stable_file_with_updated_metadata_is_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            path.write_bytes(b'{}')
            original = path.stat()
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
            self.assertEqual(scope.read_regular(path), b'{}')

    def test_windows_cross_view_keeps_creation_time_and_all_identity_fields(self):
        before = metadata()
        opened = metadata(st_ctime_ns=before.st_ctime_ns + 1)
        self.assertEqual(scope._source_signature(before, windows_cross_view=True),
                         scope._source_signature(opened, windows_cross_view=True))
        for field in ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size',
                      'st_mtime_ns', 'st_birthtime_ns'):
            with self.subTest(field=field):
                different = metadata(**{field: getattr(before, field) + 1})
                self.assertNotEqual(scope._source_signature(before, windows_cross_view=True),
                                    scope._source_signature(different, windows_cross_view=True))

    def test_windows_legacy_ctime_fallback_is_strict(self):
        before, opened = metadata(), metadata()
        del before.st_birthtime_ns
        del opened.st_birthtime_ns
        self.assertEqual(scope._source_signature(before, windows_cross_view=True),
                         scope._source_signature(opened, windows_cross_view=True))
        opened.st_ctime_ns += 1
        self.assertNotEqual(scope._source_signature(before, windows_cross_view=True),
                            scope._source_signature(opened, windows_cross_view=True))

    def test_posix_cross_view_keeps_ctime(self):
        self.assertNotEqual(scope._source_signature(metadata()),
                            scope._source_signature(metadata(st_ctime_ns=metadata().st_ctime_ns + 1)))

    def test_mixed_ctime_views_keep_separate_stability_baselines(self):
        if os.name == 'nt':
            self.assertEqual(self.observed_read(opened=metadata(st_ctime_ns=metadata().st_ctime_ns + 1)), b'{}')
        else:
            # POSIX retains the original cross-view ctime comparison.
            with self.assertRaisesRegex(ValueError, 'source changed before read'):
                self.observed_read(opened=metadata(st_ctime_ns=metadata().st_ctime_ns + 1))

    def test_path_ctime_drift_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'source changed during read'):
            self.observed_read(after_path=metadata(st_ctime_ns=metadata().st_ctime_ns + 1))

    def test_descriptor_ctime_drift_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'source changed during read'):
            self.observed_read(after_fd=metadata(st_ctime_ns=metadata().st_ctime_ns + 1))

    def test_foreign_identity_before_or_after_read_is_refused(self):
        for point in ('opened', 'after_fd', 'after_path'):
            with self.subTest(point=point), self.assertRaises(ValueError):
                self.observed_read(**{point: metadata(st_ino=999)})

    def test_metadata_size_and_link_count_drift_is_refused(self):
        for field in ('st_dev', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_birthtime_ns'):
            for point in ('after_fd', 'after_path'):
                with self.subTest(field=field, point=point), self.assertRaises(ValueError):
                    changed = metadata(**{field: getattr(metadata(), field) + 1})
                    self.observed_read(**{point: changed})


if __name__ == '__main__':
    unittest.main()
