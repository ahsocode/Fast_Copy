"""
Copy Engine — Central Coordinator
===================================
Decides which strategy to use, checks preconditions, and streams
progress events back to the caller via callbacks.

Modes:
  - AUTO:   engine decides based on file count and size
  - LARGE:  always use large-file pipelined strategy
  - SMALL:  always use many-files thread pool strategy
"""

import dataclasses
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional, Tuple

from .drive_detect import get_drive_type, get_optimal_workers, get_optimal_chunk_size
from .platform_io import get_free_space, get_total_size
from .large_file import copy_large_file
from .small_files import copy_many_files, scan_total_size


# ── Threshold: file larger than this is treated as "large file" ──
LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100 MB


class CopyMode(Enum):
    AUTO = auto()
    LARGE = auto()   # Pipelined double-buffer
    SMALL = auto()   # Thread pool


@dataclass
class CopyJob:
    """Describes a copy operation."""
    sources: List[str]          # List of files/folders to copy
    destination: str            # Destination folder
    mode: CopyMode = CopyMode.AUTO


@dataclass
class CopyProgress:
    """Snapshot of copy progress emitted to UI."""
    bytes_done: int = 0
    bytes_total: int = 0
    files_done: int = 0
    files_total: int = 0
    current_file: str = ""
    speed_bps: float = 0.0      # bytes per second
    elapsed_sec: float = 0.0
    eta_sec: float = 0.0
    errors: List[Tuple[str, str]] = field(default_factory=list)
    finished: bool = False
    cancelled: bool = False


class CopyEngine:
    """
    Thread-safe copy engine.

    Usage:
        engine = CopyEngine()
        engine.start(job, on_progress=my_callback)
        # ... later:
        engine.cancel()
    """

    def __init__(self):
        self._cancel_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None

    def start(
        self,
        job: CopyJob,
        on_progress: Callable[[CopyProgress], None],
    ) -> None:
        """
        Begin copy in a background thread.
        `on_progress` is called from the worker thread — Qt worker
        should relay this via pyqtSignal.
        """
        self._cancel_event.clear()
        self._worker_thread = threading.Thread(
            target=self._run,
            args=(job, on_progress),
            daemon=True,
        )
        self._worker_thread.start()

    def cancel(self) -> None:
        """Signal the copy to stop as soon as possible."""
        self._cancel_event.set()

    def is_running(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    # ──────────────────────────────────────────────────────────────
    # Internal
    # ──────────────────────────────────────────────────────────────

    def _run(self, job: CopyJob, on_progress: Callable[[CopyProgress], None]) -> None:
        progress = CopyProgress()
        start_time = time.monotonic()
        speed_tracker = _SpeedTracker()

        # Throttle UI updates: max 20 fps (50 ms) to avoid signal flood
        _last_emit_time = [0.0]
        _emit_lock = threading.Lock()

        def emit(finished=False, cancelled=False):
            now = time.monotonic()
            with _emit_lock:
                # Always emit on terminal states; throttle intermediate updates
                if not finished and not cancelled:
                    if (now - _last_emit_time[0]) < 0.05:
                        return
                _last_emit_time[0] = now
                elapsed = now - start_time
                spd = speed_tracker.speed()
                remaining = progress.bytes_total - progress.bytes_done
                eta = remaining / spd if spd > 0 else 0.0

                # ── Emit a SNAPSHOT (not the mutable progress object) ──
                # This prevents the GUI thread from reading partially-updated
                # fields while the worker thread is still writing to them.
                snapshot = dataclasses.replace(
                    progress,
                    elapsed_sec=elapsed,
                    speed_bps=spd,
                    eta_sec=eta,
                    finished=finished,
                    cancelled=cancelled,
                    errors=list(progress.errors),   # new list — safe to read
                )
                on_progress(snapshot)

        try:
            # ── 1. Resolve all source items ───────────────────────
            resolved = _resolve_sources(job.sources)
            if not resolved:
                progress.finished = True
                emit(finished=True)
                return

            # ── 2. Compute total size ─────────────────────────────
            total_bytes = 0
            total_files = 0
            for src in resolved:
                b, f = scan_total_size(src)
                total_bytes += b
                total_files += f
            progress.bytes_total = total_bytes
            progress.files_total = total_files
            emit()

            # ── 3. Pre-flight: check free space ───────────────────
            dst = job.destination
            os.makedirs(dst, exist_ok=True)
            free = get_free_space(dst)
            if free < total_bytes:
                raise OSError(
                    f"Not enough space: need {_fmt_size(total_bytes)}, "
                    f"available {_fmt_size(free)}"
                )

            # ── 4. Determine strategy ─────────────────────────────
            mode = job.mode
            if mode == CopyMode.AUTO:
                mode = _auto_mode(resolved)

            num_workers = get_optimal_workers(resolved[0], dst)
            chunk_size = get_optimal_chunk_size(resolved[0], dst)

            # ── 5. Copy each source item ──────────────────────────
            for src in resolved:
                if self._cancel_event.is_set():
                    break

                src_name = os.path.basename(src)
                dst_path = os.path.join(dst, src_name)

                if mode == CopyMode.LARGE:
                    # Large file pipeline
                    _lf_prev = [0]

                    def large_progress_cb(bytes_written: int, _src=src):
                        delta = bytes_written - _lf_prev[0]
                        _lf_prev[0] = bytes_written
                        if delta > 0:
                            progress.bytes_done += delta
                            progress.current_file = _src
                            speed_tracker.add(delta)
                        emit()

                    try:
                        copy_large_file(
                            src, dst_path,
                            chunk_size=chunk_size,
                            progress_cb=large_progress_cb,
                            cancel_event=self._cancel_event,
                        )
                    except Exception as e:
                        # Log error, continue with next source item
                        progress.errors.append((src, str(e)))
                    progress.files_done += 1

                else:
                    # Many-files chunk-dispatch pool
                    # ── Coordinator pattern ──────────────────────
                    # Worker threads ONLY update a shared atomic counter.
                    # A single coordinator thread reads the counter and calls
                    # emit() at 20 Hz. This eliminates emit-lock contention
                    # that previously serialised all worker threads.
                    _shared_bytes = [0]
                    _shared_file  = [""]
                    _ctr_lock     = threading.Lock()
                    _coord_done   = threading.Event()
                    _prev_bytes   = [0]

                    def small_progress_cb(n_bytes: int, current: str):
                        """Hot path: called from N worker threads.
                        Just update counters — no emit, no speed_tracker."""
                        with _ctr_lock:
                            _shared_bytes[0] += n_bytes
                            if current:
                                _shared_file[0] = current

                    def _coordinator():
                        """Emits UI updates at 20 Hz regardless of worker count."""
                        while not _coord_done.wait(timeout=0.05):
                            with _ctr_lock:
                                cur  = _shared_bytes[0]
                                name = _shared_file[0]
                            delta = cur - _prev_bytes[0]
                            _prev_bytes[0] = cur
                            if delta > 0:
                                progress.bytes_done  += delta
                                progress.current_file = name
                                speed_tracker.add(delta)
                            emit()
                        # Final sync: flush any bytes counted after last tick
                        with _ctr_lock:
                            cur = _shared_bytes[0]
                        final_delta = cur - _prev_bytes[0]
                        if final_delta > 0:
                            progress.bytes_done += final_delta

                    coord_thread = threading.Thread(
                        target=_coordinator, daemon=True
                    )
                    coord_thread.start()

                    errors = copy_many_files(
                        src, dst_path,
                        num_workers=num_workers,
                        progress_cb=small_progress_cb,
                        cancel_event=self._cancel_event,
                    )

                    _coord_done.set()
                    coord_thread.join(timeout=0.5)

                    progress.files_done += 1
                    for (f, e) in errors:
                        progress.errors.append((f, str(e)))

        except Exception as e:
            progress.errors.append(("", str(e)))
            emit(finished=True)
            return

        if self._cancel_event.is_set():
            emit(cancelled=True)
        else:
            progress.bytes_done = progress.bytes_total  # ensure 100%
            emit(finished=True)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _resolve_sources(sources: List[str]) -> List[str]:
    """Return only paths that actually exist."""
    return [s for s in sources if os.path.exists(s)]


def _auto_mode(sources: List[str]) -> CopyMode:
    """
    Choose LARGE mode if there is a single large file,
    otherwise SMALL mode for directories or many files.
    """
    if len(sources) == 1 and os.path.isfile(sources[0]):
        if os.path.getsize(sources[0]) >= LARGE_FILE_THRESHOLD:
            return CopyMode.LARGE
    return CopyMode.SMALL


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


class _SpeedTracker:
    """Rolling 2-second window speed estimator."""

    def __init__(self, window: float = 2.0):
        self._window = window
        self._samples: list = []  # (timestamp, bytes)
        self._lock = threading.Lock()

    def add(self, n_bytes: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._samples.append((now, n_bytes))
            cutoff = now - self._window
            self._samples = [(t, b) for t, b in self._samples if t >= cutoff]

    def speed(self) -> float:
        """Return bytes/sec averaged over the window."""
        with self._lock:
            if not self._samples:
                return 0.0
            total_bytes = sum(b for _, b in self._samples)
            oldest = self._samples[0][0]
            newest = self._samples[-1][0]
            elapsed = newest - oldest
            if elapsed < 0.05:
                return 0.0
            return total_bytes / elapsed
