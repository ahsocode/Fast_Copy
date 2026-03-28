"""
Qt Worker Thread
=================
Bridges CopyEngine (runs in background thread) with the Qt event loop.
Uses pyqtSignal to safely update GUI from a non-main thread.

KEY FIX:
  - finished() is always emitted when copy completes (even with some errors).
  - error() is only emitted for truly fatal errors (cannot start at all).
  - finished_with_errors(list) carries the per-file error list to the GUI.
"""

import time
from PyQt5.QtCore import QThread, pyqtSignal

from core.copy_engine import CopyEngine, CopyJob, CopyProgress


class CopyWorker(QThread):
    """
    Signals:
        progress(CopyProgress)       — emitted ~20 Hz during copy
        finished()                   — copy completed, all files done
        finished_with_errors(list)   — completed but some files skipped
        cancelled()                  — user cancelled
        error(str)                   — fatal error (could not start copy at all)
    """

    progress             = pyqtSignal(object)   # CopyProgress
    finished             = pyqtSignal()
    finished_with_errors = pyqtSignal(list)      # list of (path, error_msg)
    cancelled            = pyqtSignal()
    error                = pyqtSignal(str)

    def __init__(self, job: CopyJob, parent=None):
        super().__init__(parent)
        self._job    = job
        self._engine = CopyEngine()

    def run(self):
        """Called by Qt in the worker thread."""
        def on_progress(p: CopyProgress):
            self.progress.emit(p)

            if not p.finished and not p.cancelled:
                return   # intermediate update — nothing else to do

            if p.cancelled:
                self.cancelled.emit()
                return

            # Copy finished (normally or with per-file errors)
            if p.errors:
                first_path, first_msg = p.errors[0]
                if not first_path:
                    # Empty path = engine-level fatal error (not a per-file skip)
                    self.error.emit(first_msg)
                else:
                    # Per-file errors: partial success, some files skipped
                    self.finished_with_errors.emit(list(p.errors))
            else:
                self.finished.emit()

        self._engine.start(self._job, on_progress=on_progress)
        # Block QThread until engine's internal thread finishes
        while self._engine.is_running():
            time.sleep(0.05)

    def cancel(self):
        """Request cancellation from the main thread."""
        self._engine.cancel()
