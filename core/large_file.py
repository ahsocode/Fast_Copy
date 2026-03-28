"""
Large File Copy Strategy
========================
Priority order (fastest → fallback):
  1. reflink / clonefile  — instant CoW, same volume only (APFS/Btrfs)
  2. os.sendfile          — zero-copy in kernel, no userspace buffer (macOS/Linux)
  3. Pipelined double-buffer — read thread + write thread overlapped (all platforms)

For same-volume copies: attempts reflink (instant CoW) first.
"""

import os
import sys
import platform
import threading
import queue
import time
from typing import Callable, Optional

from .platform_io import (
    open_read_fast, open_write_fast,
    copy_file_reflink, get_free_space,
)
from .win_long_path import to_extended, strip_extended

_SYSTEM = platform.system()

# Sentinel object signals end-of-file to writer thread
_EOF = object()

# sendfile chunk: 256 MB — large enough to amortise syscall overhead
_SENDFILE_CHUNK = 256 * 1024 * 1024


def copy_large_file(
    src: str,
    dst: str,
    chunk_size: int,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> None:
    """
    Copy a single large file from src to dst as fast as possible.

    Args:
        src:          Source file path.
        dst:          Destination file path (will be created/overwritten).
        chunk_size:   Read/write chunk size in bytes (e.g. 64 MB).
        progress_cb:  Called with cumulative bytes copied so far.
        cancel_event: Set this Event to abort the copy mid-way.

    Raises:
        OSError:       If src cannot be read or dst cannot be written.
        RuntimeError:  If cancelled mid-copy (dst is left partially written).
    """
    # Apply extended-length path prefix on Windows (fixes WinError 206)
    src = to_extended(src)
    dst = to_extended(dst)

    file_size = os.path.getsize(src)

    # Ensure destination directory exists
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)

    # ── 1. Try reflink first (instant on APFS / Btrfs) ──────────────
    if _same_volume(src, dst):
        if os.path.exists(dst):
            os.remove(dst)
        if copy_file_reflink(src, dst):
            if progress_cb:
                progress_cb(file_size)
            _copy_metadata(src, dst)
            return

    # ── 2. os.sendfile — zero-copy kernel path (macOS / Linux) ───────
    if _SYSTEM in ("Darwin", "Linux") and not (cancel_event and cancel_event.is_set()):
        if _copy_sendfile(src, dst, file_size, progress_cb, cancel_event):
            _copy_metadata(src, dst)
            return

    # ── 3. Pipelined double-buffer copy (universal fallback) ─────────
    _copy_pipeline(src, dst, file_size, chunk_size, progress_cb, cancel_event)
    _copy_metadata(src, dst)


# ──────────────────────────────────────────────────────────────────
# Strategy implementations
# ──────────────────────────────────────────────────────────────────

def _copy_sendfile(
    src: str,
    dst: str,
    file_size: int,
    progress_cb: Optional[Callable[[int], None]],
    cancel_event: Optional[threading.Event],
) -> bool:
    """
    Copy using os.sendfile() — data never leaves kernel space.
    Returns True on success, False on any error (caller falls through).
    """
    try:
        with open(src, "rb") as fsrc:
            with open(dst, "wb") as fdst:
                # Pre-allocate to avoid mid-write fragmentation
                try:
                    if _SYSTEM == "Darwin":
                        import fcntl, struct
                        F_PREALLOCATE = 42
                        fstore = struct.pack("iiqqi", 1, 3, 0, file_size, 0)
                        fcntl.fcntl(fdst.fileno(), F_PREALLOCATE, fstore)
                    os.ftruncate(fdst.fileno(), file_size)
                    os.lseek(fdst.fileno(), 0, os.SEEK_SET)
                except OSError:
                    pass

                offset = 0
                while offset < file_size:
                    if cancel_event and cancel_event.is_set():
                        return False
                    to_send = min(_SENDFILE_CHUNK, file_size - offset)
                    sent = os.sendfile(fdst.fileno(), fsrc.fileno(), offset, to_send)
                    if sent == 0:
                        break
                    offset += sent
                    if progress_cb:
                        progress_cb(offset)
        return True
    except Exception:
        # sendfile not available or failed — fall through to pipeline
        try:
            os.remove(dst)
        except OSError:
            pass
        return False


def _copy_pipeline(
    src: str,
    dst: str,
    file_size: int,
    chunk_size: int,
    progress_cb: Optional[Callable[[int], None]],
    cancel_event: Optional[threading.Event],
) -> None:
    """Pipelined double-buffer: reader and writer threads run concurrently."""
    # 2 slots: reader stays at most 2 chunks ahead of writer
    buf_queue: queue.Queue = queue.Queue(maxsize=2)
    error_holder: list = [None]

    def reader():
        try:
            with open_read_fast(src) as f:
                while True:
                    if cancel_event and cancel_event.is_set():
                        buf_queue.put(_EOF)
                        return
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    buf_queue.put(chunk)
            buf_queue.put(_EOF)
        except Exception as e:
            error_holder[0] = e
            buf_queue.put(_EOF)

    def writer():
        bytes_written = 0
        try:
            with open_write_fast(dst, size_hint=file_size) as f:
                while True:
                    chunk = buf_queue.get()
                    if chunk is _EOF:
                        break
                    f.write(chunk)
                    bytes_written += len(chunk)
                    if progress_cb:
                        progress_cb(bytes_written)
                    buf_queue.task_done()
        except Exception as e:
            error_holder[0] = e

    t_read  = threading.Thread(target=reader, daemon=True)
    t_write = threading.Thread(target=writer, daemon=True)
    t_read.start()
    t_write.start()
    t_read.join()
    t_write.join()

    if error_holder[0]:
        raise error_holder[0]

    if cancel_event and cancel_event.is_set():
        try:
            os.remove(dst)
        except OSError:
            pass
        raise RuntimeError("Copy cancelled by user")


def _same_volume(path_a: str, path_b: str) -> bool:
    """Return True if both paths are on the same filesystem volume."""
    try:
        # For dst, check its parent directory (file may not exist yet)
        check_b = path_b if os.path.exists(path_b) else os.path.dirname(path_b) or "."
        return os.stat(path_a).st_dev == os.stat(check_b).st_dev
    except OSError:
        return False


def _copy_metadata(src: str, dst: str) -> None:
    """Copy file modification time and permission bits."""
    try:
        st = os.stat(src)
        os.utime(dst, (st.st_atime, st.st_mtime))
        os.chmod(dst, st.st_mode)
    except OSError:
        pass
