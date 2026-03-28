"""
Main Window — PyQt5 GUI
========================
Layout:
  ┌──────────────────────────────────────────────────┐
  │  MODE: [● Auto] [○ Large File] [○ Many Files]    │
  ├────────────────────┬─────────────────────────────┤
  │  SOURCE            │  DESTINATION                │
  │  [file list]       │  [path line edit]           │
  │  [Add Files]       │  [Browse]                   │
  │  [Add Folder] [X]  │                             │
  ├────────────────────┴─────────────────────────────┤
  │  ████████████░░░░░░  67%                         │
  │  Speed: 2.3 GB/s  |  ETA: 00:12  |  1.2/3.4 GB  │
  ├──────────────────────────────────────────────────┤
  │              [START COPY]  [CANCEL]              │
  └──────────────────────────────────────────────────┘
"""

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QListWidget, QListWidgetItem, QPushButton,
    QLineEdit, QLabel, QProgressBar, QRadioButton,
    QButtonGroup, QFileDialog, QMessageBox, QSizePolicy,
    QAbstractItemView, QFrame, QSplitter,
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

from core.copy_engine import CopyJob, CopyMode, CopyProgress
from gui.copy_worker import CopyWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker: CopyWorker = None
        self._last_pct: int = 0          # monotonic guard for progress bar
        self._setup_ui()
        self._apply_style()

    # ──────────────────────────────────────────────────────────────
    # UI Setup
    # ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle("CopySoft — High-Speed File Copier")
        self.setMinimumSize(QSize(720, 520))

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        # ── Mode selector ─────────────────────────────────────────
        mode_box = QGroupBox("Copy Mode")
        mode_layout = QHBoxLayout(mode_box)
        self._rb_auto = QRadioButton("Auto (Recommended)")
        self._rb_large = QRadioButton("Large File")
        self._rb_small = QRadioButton("Many Small Files")
        self._rb_auto.setChecked(True)

        self._mode_group = QButtonGroup()
        for rb in (self._rb_auto, self._rb_large, self._rb_small):
            self._mode_group.addButton(rb)
            mode_layout.addWidget(rb)
        mode_layout.addStretch()
        root_layout.addWidget(mode_box)

        # ── Source + Destination panels ───────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Source panel
        src_box = QGroupBox("Source")
        src_layout = QVBoxLayout(src_box)
        self._src_list = QListWidget()
        self._src_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._src_list.setMinimumHeight(160)
        src_layout.addWidget(self._src_list)

        src_btn_row = QHBoxLayout()
        self._btn_add_files = QPushButton("Add Files")
        self._btn_add_folder = QPushButton("Add Folder")
        self._btn_remove = QPushButton("Remove")
        src_btn_row.addWidget(self._btn_add_files)
        src_btn_row.addWidget(self._btn_add_folder)
        src_btn_row.addWidget(self._btn_remove)
        src_layout.addLayout(src_btn_row)
        splitter.addWidget(src_box)

        # Destination panel
        dst_box = QGroupBox("Destination")
        dst_layout = QVBoxLayout(dst_box)
        dst_inner = QHBoxLayout()
        self._dst_edit = QLineEdit()
        self._dst_edit.setPlaceholderText("Select destination folder…")
        self._btn_dst_browse = QPushButton("Browse")
        dst_inner.addWidget(self._dst_edit)
        dst_inner.addWidget(self._btn_dst_browse)
        dst_layout.addLayout(dst_inner)
        dst_layout.addStretch()
        splitter.addWidget(dst_box)

        splitter.setSizes([360, 360])
        root_layout.addWidget(splitter, stretch=1)

        # ── Separator line ────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root_layout.addWidget(sep)

        # ── Progress area ─────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 1000)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%p%")
        self._progress_bar.setFixedHeight(22)
        root_layout.addWidget(self._progress_bar)

        # Speed + size row
        self._lbl_stats = QLabel("Ready.")
        self._lbl_stats.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(self._lbl_stats)

        # Elapsed + ETA row (dedicated label so it's always visible)
        self._lbl_eta = QLabel("")
        self._lbl_eta.setAlignment(Qt.AlignCenter)
        font_eta = QFont()
        font_eta.setPointSize(11)
        font_eta.setBold(True)
        self._lbl_eta.setFont(font_eta)
        root_layout.addWidget(self._lbl_eta)

        # Current filename row
        self._lbl_file = QLabel("")
        self._lbl_file.setAlignment(Qt.AlignCenter)
        self._lbl_file.setWordWrap(True)
        font_small = QFont()
        font_small.setPointSize(9)
        self._lbl_file.setFont(font_small)
        root_layout.addWidget(self._lbl_file)

        # ── Action buttons ────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_start = QPushButton("START COPY")
        self._btn_start.setFixedHeight(36)
        self._btn_start.setMinimumWidth(160)
        self._btn_cancel = QPushButton("CANCEL")
        self._btn_cancel.setFixedHeight(36)
        self._btn_cancel.setMinimumWidth(100)
        self._btn_cancel.setEnabled(False)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch()
        root_layout.addLayout(btn_row)

        # ── Connections ───────────────────────────────────────────
        self._btn_add_files.clicked.connect(self._add_files)
        self._btn_add_folder.clicked.connect(self._add_folder)
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_dst_browse.clicked.connect(self._browse_dst)
        self._btn_start.clicked.connect(self._start_copy)
        self._btn_cancel.clicked.connect(self._cancel_copy)

        # Drag & drop on source list
        self._src_list.setAcceptDrops(True)
        self._src_list.dragEnterEvent = self._drag_enter
        self._src_list.dropEvent = self._drop_event

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: "Segoe UI", "SF Pro Text", Arial, sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 8px;
                color: #89b4fa;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QListWidget {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                color: #cdd6f4;
            }
            QListWidget::item:selected {
                background-color: #313244;
            }
            QLineEdit {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 4px 8px;
                color: #cdd6f4;
            }
            QPushButton {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px 14px;
                color: #cdd6f4;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
            QPushButton:disabled {
                color: #6c7086;
                background-color: #181825;
            }
            QPushButton#start_btn {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#start_btn:hover {
                background-color: #b4befe;
            }
            QPushButton#start_btn:disabled {
                background-color: #313244;
                color: #6c7086;
            }
            QPushButton#cancel_btn {
                background-color: #f38ba8;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#cancel_btn:hover {
                background-color: #eba0ac;
            }
            QPushButton#cancel_btn:disabled {
                background-color: #313244;
                color: #6c7086;
            }
            QProgressBar {
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #181825;
                text-align: center;
                color: #cdd6f4;
            }
            QProgressBar::chunk {
                background-color: #89b4fa;
                border-radius: 3px;
            }
            QRadioButton {
                spacing: 6px;
            }
            QRadioButton::indicator {
                width: 14px;
                height: 14px;
            }
            QSplitter::handle {
                background-color: #313244;
                width: 1px;
            }
            QFrame[frameShape="4"] {
                color: #313244;
            }
            QLabel {
                color: #a6adc8;
            }
        """)
        self._btn_start.setObjectName("start_btn")
        self._btn_cancel.setObjectName("cancel_btn")
        # Re-apply style after setting object names
        self._btn_start.style().unpolish(self._btn_start)
        self._btn_start.style().polish(self._btn_start)
        self._btn_cancel.style().unpolish(self._btn_cancel)
        self._btn_cancel.style().polish(self._btn_cancel)

    # ──────────────────────────────────────────────────────────────
    # Source management
    # ──────────────────────────────────────────────────────────────

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Files")
        for p in paths:
            self._add_source(p)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            self._add_source(path)

    def _add_source(self, path: str):
        # Avoid duplicates
        existing = [
            self._src_list.item(i).data(Qt.UserRole)
            for i in range(self._src_list.count())
        ]
        if path in existing:
            return
        item = QListWidgetItem(path)
        item.setData(Qt.UserRole, path)
        self._src_list.addItem(item)

    def _remove_selected(self):
        for item in self._src_list.selectedItems():
            self._src_list.takeItem(self._src_list.row(item))

    # ──────────────────────────────────────────────────────────────
    # Destination
    # ──────────────────────────────────────────────────────────────

    def _browse_dst(self):
        path = QFileDialog.getExistingDirectory(self, "Select Destination Folder")
        if path:
            self._dst_edit.setText(path)

    # ──────────────────────────────────────────────────────────────
    # Drag & Drop on source list
    # ──────────────────────────────────────────────────────────────

    def _drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _drop_event(self, event):
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._add_source(local)

    # ──────────────────────────────────────────────────────────────
    # Copy actions
    # ──────────────────────────────────────────────────────────────

    def _start_copy(self):
        sources = [
            self._src_list.item(i).data(Qt.UserRole)
            for i in range(self._src_list.count())
        ]
        dst = self._dst_edit.text().strip()

        if not sources:
            QMessageBox.warning(self, "No Source", "Please add at least one source file or folder.")
            return
        if not dst:
            QMessageBox.warning(self, "No Destination", "Please select a destination folder.")
            return
        if not os.path.exists(dst) and not self._confirm_create_dst(dst):
            return

        mode = CopyMode.AUTO
        if self._rb_large.isChecked():
            mode = CopyMode.LARGE
        elif self._rb_small.isChecked():
            mode = CopyMode.SMALL

        job = CopyJob(sources=sources, destination=dst, mode=mode)

        self._worker = CopyWorker(job)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished_with_errors.connect(self._on_finished_with_errors)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.error.connect(self._on_error)
        self._worker.start()

        self._btn_start.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._last_pct = 0
        self._progress_bar.setValue(0)
        self._lbl_stats.setText("Starting…")
        self._lbl_eta.setText("")
        self._lbl_file.setText("")

    def _cancel_copy(self):
        if self._worker:
            self._worker.cancel()
        self._btn_cancel.setEnabled(False)

    def _confirm_create_dst(self, dst: str) -> bool:
        reply = QMessageBox.question(
            self, "Create Folder?",
            f"Destination does not exist:\n{dst}\n\nCreate it?",
            QMessageBox.Yes | QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    # ──────────────────────────────────────────────────────────────
    # Progress callbacks (called from worker thread via signal)
    # ──────────────────────────────────────────────────────────────

    def _on_progress(self, p: CopyProgress):
        # ── Progress bar (monotonic — never go backwards) ─────────
        if p.bytes_total > 0:
            pct = int(p.bytes_done / p.bytes_total * 1000)
            pct = min(1000, max(0, pct))
            if pct >= self._last_pct:       # only advance, never retreat
                self._last_pct = pct
                self._progress_bar.setValue(pct)

        # ── Stats row: speed + size ────────────────────────────────
        speed_str = _fmt_speed(p.speed_bps)
        done_str  = _fmt_size(p.bytes_done)
        total_str = _fmt_size(p.bytes_total)
        files_str = (f"{p.files_done}/{p.files_total} items"
                     if p.files_total > 0 else "")
        self._lbl_stats.setText(
            f"Speed: {speed_str}  ·  {done_str} / {total_str}"
            + (f"  ·  {files_str}" if files_str else "")
        )

        # ── ETA row: elapsed + estimated remaining ─────────────────
        elapsed_str = _fmt_time(p.elapsed_sec)
        eta_str     = _fmt_time(p.eta_sec)
        if p.elapsed_sec > 0 or p.eta_sec > 0:
            self._lbl_eta.setText(
                f"Elapsed: {elapsed_str}  ·  Còn lại: {eta_str}"
            )

        # ── Current file row ───────────────────────────────────────
        if p.current_file:
            name = os.path.basename(p.current_file)
            self._lbl_file.setText(f"Đang copy: {name}")

    def _on_finished(self):
        self._last_pct = 1000
        self._progress_bar.setValue(1000)
        self._lbl_stats.setText("Hoàn thành!")
        self._lbl_eta.setText("")
        self._lbl_file.setText("")
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        QMessageBox.information(self, "Hoàn thành", "Copy hoàn thành thành công!")

    def _on_finished_with_errors(self, errors: list):
        """Copy finished but some files were skipped — show summary."""
        self._last_pct = 1000
        self._progress_bar.setValue(1000)
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)

        n = len(errors)
        self._lbl_stats.setText(f"Hoàn thành — bỏ qua {n} file lỗi.")
        self._lbl_eta.setText("")
        self._lbl_file.setText("")

        # Build summary message (show first 20 errors, then count)
        lines = [f"Copy completed — {n} file(s) could not be copied:\n"]
        for path, msg in errors[:20]:
            short = os.path.basename(path) if path else "unknown"
            lines.append(f"  • {short}\n    {msg}")
        if n > 20:
            lines.append(f"\n  … and {n - 20} more.")
        lines.append("\nAll other files were copied successfully.")

        # Use a scrollable dialog for long lists
        from PyQt5.QtWidgets import QDialog, QTextEdit, QVBoxLayout, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Completed with {n} error(s)")
        dlg.setMinimumSize(600, 360)
        layout = QVBoxLayout(dlg)
        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText("\n".join(lines))
        txt.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(txt)
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn)
        dlg.exec_()

    def _on_cancelled(self):
        self._lbl_stats.setText("Đã huỷ.")
        self._lbl_eta.setText("")
        self._lbl_file.setText("")
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)

    def _on_error(self, msg: str):
        """Fatal error — could not copy anything at all."""
        self._lbl_stats.setText("Lỗi!")
        self._lbl_eta.setText("")
        self._lbl_file.setText("")
        self._btn_start.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        QMessageBox.critical(self, "Lỗi Copy", msg)

    # ──────────────────────────────────────────────────────────────
    # Window close guard
    # ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "Copy in Progress",
                "A copy is running. Cancel and quit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._worker.cancel()
                self._worker.wait(3000)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ──────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    return _fmt_size(int(bps)) + "/s"


def _fmt_time(sec: float) -> str:
    if sec <= 0:
        return "—"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
