"""
Browse & Select Dialog — in-app file browser with checkboxes.

Allows navigating the filesystem and checking multiple files/folders
before adding them to the source list. Checked state is preserved
across navigation so the user can pick from different directories.
"""

import os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QLineEdit, QLabel, QAbstractItemView, QSizePolicy,
    QHeaderView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class BrowseDialog(QDialog):
    """Modal dialog with a filesystem tree and per-item checkboxes.

    After exec_(), call .selected_paths() to get the list of checked entries.
    """

    def __init__(self, parent=None, start_dir: str = None):
        super().__init__(parent)
        self.setWindowTitle("Browse & Select Files / Folders")
        self.setMinimumSize(700, 500)
        self.resize(800, 560)

        # Persistent set of checked absolute paths (survives navigation)
        self._checked: set = set()
        # Current directory being shown
        self._current_dir: str = start_dir or os.path.expanduser("~")

        self._build_ui()
        self._apply_style()
        self._navigate(self._current_dir)

    # ──────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # ── Path bar ──────────────────────────────────────────────
        path_row = QHBoxLayout()
        self._btn_up = QPushButton("↑ Up")
        self._btn_up.setFixedWidth(60)
        self._btn_up.clicked.connect(self._go_up)

        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setFont(QFont("Courier New", 11))

        path_row.addWidget(self._btn_up)
        path_row.addWidget(self._path_edit)
        layout.addLayout(path_row)

        # ── Tree widget ───────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Name", "Type", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._tree.setSelectionMode(QAbstractItemView.NoSelection)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)

        # Double-click to navigate into folders
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        # Checkbox state changed
        self._tree.itemChanged.connect(self._on_item_changed)

        layout.addWidget(self._tree, stretch=1)

        # ── Selection info ────────────────────────────────────────
        self._lbl_count = QLabel("0 items selected")
        self._lbl_count.setAlignment(Qt.AlignRight)
        layout.addWidget(self._lbl_count)

        # ── Bulk action buttons ───────────────────────────────────
        bulk_row = QHBoxLayout()
        self._btn_all = QPushButton("Select All")
        self._btn_none = QPushButton("Clear All")
        self._btn_all.clicked.connect(self._select_all)
        self._btn_none.clicked.connect(self._clear_all)

        bulk_row.addWidget(self._btn_all)
        bulk_row.addWidget(self._btn_none)
        bulk_row.addStretch()
        layout.addLayout(bulk_row)

        # ── Dialog buttons ────────────────────────────────────────
        dlg_row = QHBoxLayout()
        dlg_row.addStretch()
        self._btn_add = QPushButton("Add Selected")
        self._btn_add.setObjectName("add_btn")
        self._btn_add.setMinimumWidth(130)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setMinimumWidth(80)
        self._btn_add.clicked.connect(self.accept)
        self._btn_cancel.clicked.connect(self.reject)

        dlg_row.addWidget(self._btn_add)
        dlg_row.addWidget(self._btn_cancel)
        layout.addLayout(dlg_row)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog, QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: "Segoe UI", "SF Pro Text", Arial, sans-serif;
                font-size: 13px;
            }
            QTreeWidget {
                background-color: #181825;
                alternate-background-color: #1e1e2e;
                border: 1px solid #313244;
                border-radius: 4px;
                color: #cdd6f4;
            }
            QTreeWidget::item:hover {
                background-color: #313244;
            }
            QHeaderView::section {
                background-color: #313244;
                color: #89b4fa;
                border: none;
                padding: 4px 8px;
            }
            QLineEdit {
                background-color: #181825;
                border: 1px solid #313244;
                border-radius: 4px;
                padding: 4px 8px;
                color: #a6adc8;
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
            QPushButton#add_btn {
                background-color: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#add_btn:hover {
                background-color: #b4befe;
            }
            QLabel {
                color: #a6adc8;
            }
        """)

    # ──────────────────────────────────────────────────────────────
    # Navigation
    # ──────────────────────────────────────────────────────────────

    def _navigate(self, path: str):
        """Load directory listing into the tree."""
        if not os.path.isdir(path):
            return
        self._current_dir = path
        self._path_edit.setText(path)

        # Block signals while rebuilding to prevent spurious itemChanged
        self._tree.blockSignals(True)
        self._tree.clearContents()
        self._tree.setRowCount(0) if hasattr(self._tree, 'setRowCount') else None
        self._tree.clear()

        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            self._tree.blockSignals(False)
            return

        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
            except OSError:
                is_dir = False
                size = 0

            name = entry.name
            kind = "Folder" if is_dir else "File"
            size_str = "" if is_dir else _fmt_size(size)
            abs_path = os.path.normpath(entry.path)

            item = QTreeWidgetItem(self._tree)
            item.setText(0, name)
            item.setText(1, kind)
            item.setText(2, size_str)
            item.setData(0, Qt.UserRole, abs_path)
            item.setData(0, Qt.UserRole + 1, is_dir)

            # Restore check state from persistent set
            checked = abs_path in self._checked
            item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

            # Style folders differently
            if is_dir:
                for col in range(3):
                    item.setForeground(col, _color_folder())

        self._tree.blockSignals(False)
        self._update_count_label()

    def _go_up(self):
        parent = os.path.dirname(self._current_dir)
        if parent != self._current_dir:
            self._navigate(parent)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int):
        is_dir = item.data(0, Qt.UserRole + 1)
        if is_dir:
            path = item.data(0, Qt.UserRole)
            self._navigate(path)

    # ──────────────────────────────────────────────────────────────
    # Checkbox management
    # ──────────────────────────────────────────────────────────────

    def _on_item_changed(self, item: QTreeWidgetItem, col: int):
        if col != 0:
            return
        path = item.data(0, Qt.UserRole)
        if path is None:
            return
        if item.checkState(0) == Qt.Checked:
            self._checked.add(path)
        else:
            self._checked.discard(path)
        self._update_count_label()

    def _select_all(self):
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
            path = item.data(0, Qt.UserRole)
            if path:
                self._checked.add(path)
        self._tree.blockSignals(False)
        self._update_count_label()

    def _clear_all(self):
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            path = item.data(0, Qt.UserRole)
            item.setCheckState(0, Qt.Unchecked)
            if path:
                self._checked.discard(path)
        self._tree.blockSignals(False)
        self._update_count_label()

    def _update_count_label(self):
        n = len(self._checked)
        self._lbl_count.setText(
            f"{n} item{'s' if n != 1 else ''} selected"
        )
        self._btn_add.setEnabled(n > 0)
        self._btn_add.setText(f"Add {n} Selected" if n > 0 else "Add Selected")

    # ──────────────────────────────────────────────────────────────
    # Result
    # ──────────────────────────────────────────────────────────────

    def selected_paths(self) -> list:
        """Return sorted list of checked absolute paths."""
        return sorted(self._checked)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _fmt_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _color_folder():
    from PyQt5.QtGui import QBrush, QColor
    return QBrush(QColor("#89b4fa"))
