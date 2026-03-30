# ⚡ Fast_Copy

> High-speed portable file copier for macOS & Windows — built for maximum throughput on both large files and thousands of small files.

![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-blue)
![Python](https://img.shields.io/badge/python-3.11-blue)
![GUI](https://img.shields.io/badge/GUI-PyQt5-green)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

- 🚀 **Maximum copy speed** — auto-selects best I/O strategy per file type and drive
- 🖥️ **Simple GUI** — drag-and-drop source, one-click destination, live progress
- 📂 **Browse & Select** — in-app filesystem browser with checkboxes; pick files from multiple directories before copying
- 📦 **Portable** — single `.exe` (Windows) or `.app` (macOS), no install needed
- 🔁 **Skip-on-error** — bad files are skipped, copy continues; full error report at end
- 🗂️ **Long path support** — handles Windows paths > 260 characters (WinError 206 fix)
- ⏱️ **Live stats** — speed, elapsed time, estimated time remaining (ETA)

---

## 📸 Screenshot

```
┌──────────────────────────────────────────────────────┐
│  Copy Mode: [● Auto] [○ Large File] [○ Many Files]   │
├─────────────────────┬────────────────────────────────┤
│  SOURCE             │  DESTINATION                   │
│  ┌───────────────┐  │  /Volumes/Backup      [Browse] │
│  │ videos/       │  │                                │
│  │ photos/       │  │                                │
│  │ project.zip   │  │                                │
│  └───────────────┘  │                                │
│  [Add Files] [Add Folder] [Browse & Select…] [Remove] │
├──────────────────────────────────────────────────────┤
│  ████████████████░░░░  78%                           │
│  Speed: 2.3 GB/s  ·  7.8 GB / 10.0 GB  ·  3/5 items │
│  Elapsed: 00:15  ·  Còn lại: 00:08                  │
│  Đang copy: bao_cao_thang_3.xlsx                     │
├──────────────────────────────────────────────────────┤
│            [  START COPY  ]   [  CANCEL  ]           │
└──────────────────────────────────────────────────────┘
```

---

## 🧠 How It Works

Fast_Copy automatically detects the best copy strategy:

### Large File Mode (> 100 MB, single file)
| Priority | Strategy | When |
|----------|----------|------|
| 1 | **Reflink / clonefile** | Same volume on APFS (macOS) or Btrfs/XFS (Linux) — instant copy-on-write |
| 2 | **os.sendfile()** | Cross-volume on macOS/Linux — zero-copy in kernel space |
| 3 | **Pipelined double-buffer** | Universal fallback — reader & writer threads run in parallel |

### Many Files Mode (directories / multiple files)
- **Chunk-dispatch thread pool** — file list split into N equal slices, each thread owns its slice
- **Coordinator pattern** — worker threads only update atomic counters; a single coordinator thread emits UI updates at 20 Hz — eliminates lock contention
- **shutil.copy2** for files ≤ 4 MB (OS-optimised path)
- **Buffered manual copy** (1 MB chunks) for larger files with cancel support

### Drive Detection
- Detects SSD / HDD / NVMe per volume (`diskutil` on macOS, `DeviceIoControl` on Windows)
- Selects optimal worker count and chunk size per drive type
- Results cached by OS device ID (`lru_cache`) to avoid repeated subprocess overhead

---

## 📂 Browse & Select

Click **Browse & Select…** in the source panel to open the in-app filesystem browser:

- Folders listed first, then files alphabetically with size info
- Check any combination of files and folders across multiple directories
- Double-click a folder to navigate into it; **↑ Up** button to go back
- **Select All / Clear All** bulk actions
- Checked state persists across navigation — pick from multiple directories, then click **Add N Selected** to add them all at once

---

## 📥 Download (Portable)

| Platform | File | Notes |
|----------|------|-------|
| Windows | `Fast_Copy.exe` | No install — double-click to run |
| macOS | `Fast_Copy-macOS.zip` | Extract → double-click `Fast_Copy.app` |

> Download from the [**Releases**](../../releases) page.

---

## 🛠️ Run from Source

### Requirements
```
Python 3.11+
PyQt5
```

### Install & Run
```bash
git clone https://github.com/ahsocode/Fast_Copy.git
cd Fast_Copy
pip install -r requirements.txt
python main.py
```

---

## 📦 Build Portable Executable

### macOS
```bash
chmod +x build/build_macos.sh
./build/build_macos.sh
# Output: dist/CopySoft
```

### Windows (native)
```bat
build\build_windows.bat
:: Output: dist\CopySoft.exe
```

### Windows exe from macOS (via Docker + Wine)
```bash
# Requires Docker Desktop
chmod +x build/build_windows_docker.sh
./build/build_windows_docker.sh
# Output: dist/CopySoft.exe
```

---

## 🔄 CI/CD — Automated Builds

Pushing a version tag triggers GitHub Actions to automatically build both binaries and publish a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Artifacts produced:
- `CopySoft.exe` — Windows portable executable
- `CopySoft` — macOS binary

---

## 📁 Project Structure

```
Fast_Copy/
├── main.py                     # Entry point
├── requirements.txt
├── copysoft.spec               # PyInstaller build spec
│
├── core/
│   ├── copy_engine.py          # Central coordinator — picks strategy, streams progress
│   ├── large_file.py           # Large file: reflink → sendfile → pipeline
│   ├── small_files.py          # Many files: chunk-dispatch thread pool
│   ├── drive_detect.py         # SSD/HDD/NVMe detection + optimal params
│   ├── platform_io.py          # Low-level I/O: reflink, unbuffered, F_NOCACHE
│   └── win_long_path.py        # Windows \\?\ long-path prefix (fixes WinError 206)
│
├── gui/
│   ├── main_window.py          # PyQt5 main window
│   ├── browse_dialog.py        # In-app filesystem browser with checkboxes
│   └── copy_worker.py          # QThread bridge — relays engine events to GUI
│
├── build/
│   ├── Dockerfile.windows      # Wine-based cross-compile environment
│   ├── build_macos.sh
│   ├── build_windows.bat
│   └── build_windows_docker.sh
│
├── .github/
│   └── workflows/build.yml     # CI: auto-build on tag push
│
└── benchmark.py                # Performance benchmark vs system cp / shutil
```

---

## ⚙️ Copy Modes

| Mode | Best for |
|------|---------|
| **Auto** (default) | Recommended — engine decides based on file count and size |
| **Large File** | Copying a single large file (ISO, video, disk image, etc.) |
| **Many Small Files** | Copying source code trees, photo libraries, project folders |

---

## 🐛 Known Fixes

| Issue | Fix |
|-------|-----|
| WinError 206 — path too long | Auto-applied `\\?\` prefix for paths > 260 chars |
| Copy aborts on one bad file | Skip-on-error: bad files logged, copy continues |
| Progress bar jumping / resetting | Emits immutable CopyProgress snapshot per tick |
| High lock contention with many threads | Coordinator pattern: workers never call emit |
| diskutil called repeatedly (400ms overhead) | Cached by `st_dev` via `lru_cache` |

---

## 📊 Benchmark

Run the included benchmark to compare against system `cp` and Python `shutil`:

```bash
python benchmark.py
```

Sample results (Apple M-series SSD, same volume):

| Test | shutil | system cp | Fast_Copy |
|------|--------|-----------|-----------|
| 1 × 1 GB file | 1.8 GB/s | 2.1 GB/s | **3.4 GB/s** |
| 500 × 2 MB files | 420 MB/s | 510 MB/s | **980 MB/s** |
| 10,000 × 50 KB files | 180 MB/s | 220 MB/s | **610 MB/s** |

> Results vary by hardware and OS caching state.

---

## 📄 License

MIT © 2025 ahsocode
