"""
CopySoft — High-Speed File Copier
Entry point: launches the Qt application.
"""

import sys
import os

# Ensure project root is on sys.path so imports work both
# when running from source and from PyInstaller bundle.
if getattr(sys, "frozen", False):
    # PyInstaller bundle: _MEIPASS is the temp extraction dir
    BASE_DIR = sys._MEIPASS  # type: ignore[attr-defined]
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from gui.main_window import MainWindow


def main():
    # Enable high-DPI scaling (important for Retina / 4K screens)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("CopySoft")
    app.setOrganizationName("CopySoft")

    # Set app icon if bundled
    icon_path = os.path.join(BASE_DIR, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
