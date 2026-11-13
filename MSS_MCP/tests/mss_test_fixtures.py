"""Bounded teardown for test-owned Windows temporary directories."""

from pathlib import Path
import stat
import time


def add_owned_directory_cleanup(test, fixture):
    path = Path(fixture.name)
    parent = path.parent.resolve(strict=True)
    root = path.resolve(strict=True)
    identity = path.stat()
    if root.parent != parent:
        raise ValueError("Unexpected temporary fixture directory")

    def cleanup():
        for attempt in range(4):
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                return
            if (path.resolve(strict=True) != root or not stat.S_ISDIR(metadata.st_mode)
                    or (metadata.st_dev, metadata.st_ino) != (identity.st_dev, identity.st_ino)
                    or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise ValueError("Temporary fixture directory changed before cleanup")
            try:
                fixture.cleanup()
            except OSError as error:
                if getattr(error, "winerror", None) != 145 or attempt == 3:
                    raise
                time.sleep(0.075)
            else:
                return

    test.addCleanup(cleanup)
