"""
Platform-specific I/O helpers.
Provides fast open/read/write using OS-level bypass where available:
  - macOS: F_NOCACHE to bypass page cache for large sequential I/O
  - Windows: FILE_FLAG_NO_BUFFERING + FILE_FLAG_WRITE_THROUGH
  - Fallback: standard buffered I/O (works everywhere)
"""

import os
import sys
import platform
import ctypes
from typing import BinaryIO, Optional


SYSTEM = platform.system()

# Alignment required for unbuffered I/O on Windows (sector size)
WINDOWS_SECTOR_ALIGN = 4096


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def open_read_fast(path: str) -> BinaryIO:
    """Open file for fast sequential reading."""
    if SYSTEM == "Darwin":
        return _open_macos_nocache(path, write=False)
    elif SYSTEM == "Windows":
        return _open_windows_unbuffered(path, write=False)
    else:
        return open(path, "rb", buffering=0)


def open_write_fast(path: str, size_hint: int = 0) -> BinaryIO:
    """
    Open file for fast sequential writing.
    Optionally pre-allocates `size_hint` bytes to reduce fragmentation.
    """
    if SYSTEM == "Darwin":
        f = _open_macos_nocache(path, write=True)
        if size_hint > 0:
            _preallocate_macos(f, size_hint)
        return f
    elif SYSTEM == "Windows":
        f = _open_windows_unbuffered(path, write=True)
        if size_hint > 0:
            _preallocate_windows(f, size_hint)
        return f
    else:
        f = open(path, "wb", buffering=0)
        if size_hint > 0:
            _preallocate_posix(f, size_hint)
        return f


def open_read_standard(path: str) -> BinaryIO:
    """Standard buffered read — used for small files."""
    return open(path, "rb")


def open_write_standard(path: str) -> BinaryIO:
    """Standard buffered write — used for small files."""
    return open(path, "wb")


def aligned_buffer(size: int) -> bytearray:
    """
    Return a bytearray suitable for unbuffered I/O.
    On Windows unbuffered I/O requires buffer aligned to sector boundary.
    On other platforms any buffer works; we still return aligned for consistency.
    """
    # Over-allocate by WINDOWS_SECTOR_ALIGN and slice to alignment
    buf = bytearray(size + WINDOWS_SECTOR_ALIGN)
    offset = (-id(buf)) % WINDOWS_SECTOR_ALIGN  # alignment offset trick
    return memoryview(buf)[offset: offset + size]  # type: ignore[return-value]


def copy_file_reflink(src: str, dst: str) -> bool:
    """
    Attempt a reflink (copy-on-write) copy. Returns True if succeeded.
    Only works when src and dst are on the same APFS/Btrfs/XFS volume.
    This is nearly instant regardless of file size.
    """
    if SYSTEM == "Darwin":
        return _reflink_macos(src, dst)
    elif SYSTEM == "Linux":
        return _reflink_linux(src, dst)
    return False


def get_free_space(path: str) -> int:
    """Return free space in bytes on the volume containing `path`."""
    if SYSTEM == "Windows":
        free = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            os.path.splitdrive(os.path.abspath(path))[0] + "\\",
            None, None, ctypes.byref(free)
        )
        return free.value
    else:
        st = os.statvfs(path)
        return st.f_bavail * st.f_frsize


def get_total_size(path: str) -> int:
    """
    Return total size of a file or all files under a directory (bytes).
    """
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ──────────────────────────────────────────────────────────────
# macOS implementations
# ──────────────────────────────────────────────────────────────

def _open_macos_nocache(path: str, write: bool) -> BinaryIO:
    """Open file and disable page cache via F_NOCACHE fcntl."""
    try:
        import fcntl
        F_NOCACHE = 48  # macOS-specific
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC if write else os.O_RDONLY
        fd = os.open(path, flags, 0o666)
        try:
            fcntl.fcntl(fd, F_NOCACHE, 1)
        except OSError:
            pass  # Not fatal; fall through with cache enabled
        return os.fdopen(fd, "wb" if write else "rb", buffering=0)
    except Exception:
        mode = "wb" if write else "rb"
        return open(path, mode, buffering=0)


def _preallocate_macos(f: BinaryIO, size: int) -> None:
    """Pre-allocate disk space on macOS using F_PREALLOCATE."""
    try:
        import fcntl
        import struct
        F_PREALLOCATE = 42
        F_PEOFPOSMODE = 3
        # struct fstore_t: flags(u32), posmode(i32), offset(i64), length(i64), bytesalloc(i64)
        fstore = struct.pack("iiqqi", 1, F_PEOFPOSMODE, 0, size, 0)
        fcntl.fcntl(f.fileno(), F_PREALLOCATE, fstore)
        os.ftruncate(f.fileno(), size)
        os.lseek(f.fileno(), 0, os.SEEK_SET)
    except Exception:
        pass


def _reflink_macos(src: str, dst: str) -> bool:
    """Use clonefile() syscall for instant CoW copy on APFS.

    Fix: was using "libc.dylib" which fails on some macOS versions.
    ctypes.CDLL(None) loads the default C runtime correctly on all macOS.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)  # default C runtime
        # clonefile(const char *src, const char *dst, uint32_t flags)
        libc.clonefile.restype  = ctypes.c_int
        libc.clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        ret = libc.clonefile(
            src.encode("utf-8"), dst.encode("utf-8"), ctypes.c_uint32(0)
        )
        return ret == 0
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# Windows implementations
# ──────────────────────────────────────────────────────────────

def _open_windows_unbuffered(path: str, write: bool) -> BinaryIO:
    """
    Open file with FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH.
    Falls back to standard open if it fails.
    """
    try:
        import msvcrt

        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x1
        OPEN_EXISTING = 3
        CREATE_ALWAYS = 2
        FILE_FLAG_NO_BUFFERING = 0x20000000
        FILE_FLAG_WRITE_THROUGH = 0x80000000
        FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000

        access = GENERIC_WRITE if write else GENERIC_READ
        creation = CREATE_ALWAYS if write else OPEN_EXISTING
        flags = FILE_FLAG_NO_BUFFERING | FILE_FLAG_SEQUENTIAL_SCAN
        if write:
            flags |= FILE_FLAG_WRITE_THROUGH

        handle = ctypes.windll.kernel32.CreateFileW(
            path, access, FILE_SHARE_READ,
            None, creation, flags, None
        )
        INVALID_HANDLE = ctypes.wintypes.HANDLE(-1).value
        if handle == INVALID_HANDLE:
            raise OSError("CreateFileW failed")

        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY if write else os.O_RDONLY)
        return os.fdopen(fd, "wb" if write else "rb", buffering=0)
    except Exception:
        mode = "wb" if write else "rb"
        return open(path, mode, buffering=0)


def _preallocate_windows(f: BinaryIO, size: int) -> None:
    """Pre-allocate file size on Windows using SetEndOfFile."""
    try:
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-11)  # not right, use fileno
        # Use SetFilePointerEx + SetEndOfFile
        kernel32 = ctypes.windll.kernel32
        # Get OS handle from fd
        import msvcrt
        os_handle = msvcrt.get_osfhandle(f.fileno())
        dist = ctypes.c_longlong(size)
        kernel32.SetFilePointerEx(os_handle, dist, None, 0)  # FILE_BEGIN=0
        kernel32.SetEndOfFile(os_handle)
        kernel32.SetFilePointerEx(os_handle, ctypes.c_longlong(0), None, 0)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────
# Linux/POSIX fallback
# ──────────────────────────────────────────────────────────────

def _preallocate_posix(f: BinaryIO, size: int) -> None:
    """Pre-allocate using fallocate (Linux) or ftruncate (fallback)."""
    try:
        import fcntl
        FALLOC_FL_KEEP_SIZE = 1
        # fallocate syscall via ctypes on Linux
        if platform.system() == "Linux":
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            libc.fallocate(f.fileno(), 0, ctypes.c_longlong(0), ctypes.c_longlong(size))
        else:
            os.ftruncate(f.fileno(), size)
            os.lseek(f.fileno(), 0, os.SEEK_SET)
    except Exception:
        pass


def _reflink_linux(src: str, dst: str) -> bool:
    """Use FICLONE ioctl for reflink copy on Btrfs/XFS.

    Fix: fcntl was used without being imported in this scope.
    """
    try:
        import fcntl  # must import here — not available at module level on all platforms
        FICLONE = 0x40049409
        with open(src, "rb") as fsrc:
            with open(dst, "wb") as fdst:
                ret = fcntl.ioctl(fdst.fileno(), FICLONE, fsrc.fileno())
                return ret == 0
    except Exception:
        return False
