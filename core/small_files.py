"""
Many Small Files Copy Strategy
================================
KEY CHANGES:
  - Chunk-dispatch thread pool (no per-file queue overhead)
  - Windows long-path support: \\?\ prefix for paths > 260 chars
  - Skip-on-error: individual file failures are logged, copy continues
  - Threshold 4 MB, buffer 1 MB
"""

import os
import sys
import shutil
import threading
from typing import Callable, List, Optional, Tuple

from .win_long_path import to_extended, strip_extended

# Files at-or-below threshold → shutil.copy2 (OS-optimised path)
_SMALL_THRESHOLD = 4 * 1024 * 1024   # 4 MB

# Buffer for manual copy path (files > 4 MB)
_COPY_BUF_SIZE   = 1 * 1024 * 1024   # 1 MB


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────

def copy_many_files(
    src: str,
    dst: str,
    num_workers: int,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> List[Tuple[str, str]]:
    """
    Copy all files from src (file or directory) to dst using chunk-dispatch
    thread pool.  Individual file errors are collected and returned — the copy
    ALWAYS continues to the next file (no abort on single failure).

    Returns:
        List of (filepath, error_message) for any files that failed.
    """
    if os.path.isfile(src):
        errors = []
        try:
            _copy_one(src, dst, progress_cb, cancel_event)
        except Exception as e:
            errors.append((src, _friendly_error(e)))
        return errors

    # ── Scan + pre-create dirs ────────────────────────────────────
    file_pairs = _scan(src, dst)
    if not file_pairs:
        return []

    # Pre-create all destination dirs (including long-path versions)
    _pre_create_dirs(file_pairs)

    # ── Chunk-dispatch: divide list into num_workers equal slices ─
    chunks = _split_chunks(file_pairs, num_workers)

    errors: List[Tuple[str, str]] = []
    errors_lock = threading.Lock()

    def worker(chunk: List[Tuple[str, str]]):
        for src_file, dst_file in chunk:
            if cancel_event and cancel_event.is_set():
                break
            try:
                _copy_one(src_file, dst_file, progress_cb, cancel_event)
            except Exception as e:
                with errors_lock:
                    errors.append((src_file, _friendly_error(e)))
                # ── SKIP and CONTINUE — do NOT abort the whole copy ──

    threads = [
        threading.Thread(target=worker, args=(chunk,), daemon=True)
        for chunk in chunks if chunk
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return errors


def scan_total_size(src: str) -> Tuple[int, int]:
    """Return (total_bytes, total_files) for src path."""
    if os.path.isfile(src):
        try:
            return os.path.getsize(to_extended(src)), 1
        except OSError:
            return 0, 1

    total_bytes = total_files = 0
    for root, _dirs, files in os.walk(to_extended(src), followlinks=False):
        for f in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, f))
                total_files += 1
            except OSError:
                pass
    return total_bytes, total_files


# ──────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────

def _scan(src_dir: str, dst_dir: str) -> List[Tuple[str, str]]:
    """
    Build (src_file, dst_file) pair list.
    Uses extended-length paths on Windows so os.walk handles deep trees.
    """
    pairs   = []
    src_ext = to_extended(os.path.normpath(src_dir))
    dst_ext = to_extended(os.path.normpath(dst_dir))

    for root, _dirs, files in os.walk(src_ext, followlinks=False):
        # Compute relative path from src_ext root
        try:
            rel = os.path.relpath(root, src_ext)
        except ValueError:
            rel = "."
        dst_root = os.path.join(dst_ext, rel) if rel != "." else dst_ext
        for fname in files:
            pairs.append((
                os.path.join(root, fname),       # already extended
                os.path.join(dst_root, fname),   # already extended
            ))
    return pairs


def _pre_create_dirs(file_pairs: List[Tuple[str, str]]) -> None:
    """Create all destination directories upfront (extended-path safe)."""
    seen = set()
    for _, dst_file in file_pairs:
        d = os.path.dirname(dst_file)
        if d not in seen:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
            seen.add(d)


def _split_chunks(lst: list, n: int) -> List[list]:
    """Divide lst into n roughly equal contiguous chunks."""
    n    = max(1, n)
    size = max(1, (len(lst) + n - 1) // n)
    return [lst[i: i + size] for i in range(0, len(lst), size)]


def _copy_one(
    src: str,
    dst: str,
    progress_cb: Optional[Callable[[int, str], None]],
    cancel_event: Optional[threading.Event],
) -> None:
    """
    Copy a single file with extended-path support on Windows.
    src and dst may already be \\?\ prefixed (from _scan).
    """
    # Ensure extended-length prefix (idempotent)
    src_x = to_extended(src)
    dst_x = to_extended(dst)

    try:
        file_size = os.path.getsize(src_x)
    except OSError:
        file_size = 0

    # Display name without \\?\ prefix for UI
    display_src = strip_extended(src_x)

    # Files <= 4 MB: shutil.copy2 (uses OS-optimised copy internally)
    if file_size <= _SMALL_THRESHOLD:
        shutil.copy2(src_x, dst_x)
        if progress_cb:
            progress_cb(file_size, display_src)
        return

    # Larger files: manual 1 MB-chunked copy with cancel support
    with open(src_x, "rb", buffering=_COPY_BUF_SIZE) as fsrc:
        with open(dst_x, "wb", buffering=_COPY_BUF_SIZE) as fdst:
            while True:
                if cancel_event and cancel_event.is_set():
                    break
                buf = fsrc.read(_COPY_BUF_SIZE)
                if not buf:
                    break
                fdst.write(buf)
                if progress_cb:
                    progress_cb(len(buf), display_src)

    # Preserve mtime + permissions
    try:
        st = os.stat(src_x)
        os.utime(dst_x, (st.st_atime, st.st_mtime))
        os.chmod(dst_x, st.st_mode)
    except OSError:
        pass


def _friendly_error(e: Exception) -> str:
    """Return a concise, human-readable error message."""
    msg = str(e)
    if isinstance(e, OSError) and e.winerror == 206:
        return f"Path too long (WinError 206): {e.filename or msg}"
    if isinstance(e, OSError) and e.winerror == 5:
        return f"Access denied: {e.filename or msg}"
    if isinstance(e, OSError) and e.winerror == 32:
        return f"File in use by another process: {e.filename or msg}"
    return msg
