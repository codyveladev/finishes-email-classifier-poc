"""Attachment I/O helpers. Kept small and reusable so form and API routes share
the same temp-file lifecycle without duplicating cleanup logic."""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def temp_file_from_bytes(data: bytes, filename: str) -> Iterator[Path]:
    """Write bytes to a NamedTemporaryFile with the source extension preserved.

    Yields the Path; deletes on exit even if the caller raises.
    """
    suffix = Path(filename).suffix or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    tmp_path = Path(tmp.name)
    try:
        yield tmp_path
    finally:
        tmp_path.unlink(missing_ok=True)
