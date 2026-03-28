"""
CopySoft Benchmark v2 — with sendfile + fixed threshold
=========================================================
Methods compared:
  1. shutil      — Python shutil.copy2 / copytree  (mirrors Finder / Explorer)
  2. cp native   — subprocess `cp -r`  (native OS binary)
  3. copysoft auto   — engine AUTO mode (picks strategy)
  4. copysoft large  — forced large-file (sendfile → pipeline)
  5. copysoft small  — forced many-files thread pool

Test cases:
  A. Single large file  (512 MB)
  B. Single large file  (1 GB)
  C. Many small files   (500 × 1 MB  = 500 MB)
  D. Many small files   (2000 × 256 KB = 500 MB)
  E. Mixed              (50 × 5 MB + 10 × 50 MB = 750 MB)

Note on macOS page cache:
  macOS APFS aggressively caches files in RAM. Subsequent runs of the same
  file will read from RAM (~10–40 GB/s) rather than NVMe (~3–6 GB/s).
  We mitigate this by using DIFFERENT source files per run (rotate) so
  results reflect real I/O rather than cache hits.
"""

import os
import sys
import time
import shutil
import subprocess
import tempfile
import threading
import statistics
from typing import Callable, List, Tuple

# ── Add project root to path ──────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from core.copy_engine import CopyEngine, CopyJob, CopyMode, CopyProgress
from core.drive_detect import get_drive_type

# ── Config ────────────────────────────────────────────────────────
RUNS     = 3          # runs per test (take median)
WORK_DIR = tempfile.mkdtemp(prefix="copysoft_bench_")
SRC_DIR  = os.path.join(WORK_DIR, "src")
DST_BASE = os.path.join(WORK_DIR, "dst")
os.makedirs(SRC_DIR, exist_ok=True)
os.makedirs(DST_BASE, exist_ok=True)

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"
RED    = "\033[91m"
MAGENTA= "\033[95m"


# ──────────────────────────────────────────────────────────────────
# File generators
# ──────────────────────────────────────────────────────────────────

def _write_random_file(path: str, size_bytes: int):
    """Write a file filled with pseudo-random data (not easily compressible)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    chunk = os.urandom(min(4 * 1024 * 1024, size_bytes))
    written = 0
    with open(path, "wb") as f:
        while written < size_bytes:
            to_write = min(len(chunk), size_bytes - written)
            f.write(chunk[:to_write])
            written += to_write


def create_test_files():
    """
    Create RUNS copies of each test case so each benchmark run reads a
    fresh file — avoiding macOS page-cache inflation of results.
    """
    print(f"{BOLD}Creating test files ({RUNS} variants each)...{RESET}")

    # Returns dict: case_name → list of (src_path, total_bytes) per run
    cases = {}

    # ── Large files: RUNS independent files per size ─────────────
    for label, size in [("large_512mb", 512*1024*1024), ("large_1gb", 1024*1024*1024)]:
        variants = []
        for r in range(RUNS):
            p = os.path.join(SRC_DIR, f"{label}_r{r}.bin")
            if not os.path.exists(p):
                _write_random_file(p, size)
            variants.append((p, size))
        cases[label] = variants
        print(f"  {DIM}[{label}]{RESET} {RUNS} × {_fmt_size(size)}")

    # ── Small files: RUNS independent directories ─────────────────
    for label, count, fsize in [
        ("small_500x1mb",    500,  1*1024*1024),
        ("small_2000x256kb", 2000, 256*1024),
    ]:
        variants = []
        for r in range(RUNS):
            d = os.path.join(SRC_DIR, f"{label}_r{r}")
            for i in range(count):
                p = os.path.join(d, f"f{i:04d}.dat")
                if not os.path.exists(p):
                    _write_random_file(p, fsize)
            total = count * fsize
            variants.append((d, total))
        cases[label] = variants
        print(f"  {DIM}[{label}]{RESET} {RUNS} × ({count} files × {_fmt_size(fsize)})")

    # ── Mixed: RUNS independent directories ──────────────────────
    label = "mixed"
    variants = []
    for r in range(RUNS):
        d = os.path.join(SRC_DIR, f"mixed_r{r}")
        total = 0
        for i in range(50):
            p = os.path.join(d, f"med_{i:03d}.dat")
            if not os.path.exists(p): _write_random_file(p, 5*1024*1024)
            total += 5*1024*1024
        for i in range(10):
            p = os.path.join(d, f"big_{i:02d}.dat")
            if not os.path.exists(p): _write_random_file(p, 50*1024*1024)
            total += 50*1024*1024
        variants.append((d, total))
    cases[label] = variants
    print(f"  {DIM}[mixed]{RESET} {RUNS} × (50×5MB + 10×50MB)")

    print()
    return cases


# ──────────────────────────────────────────────────────────────────
# Method wrappers
# ──────────────────────────────────────────────────────────────────

def method_shutil(src: str, dst: str):
    if os.path.isfile(src):
        shutil.copy2(src, dst)
    else:
        name = os.path.basename(src)
        shutil.copytree(src, os.path.join(dst, name))


def method_cp(src: str, dst: str):
    if os.path.isfile(src):
        subprocess.run(["cp", src, dst], check=True, capture_output=True)
    else:
        subprocess.run(["cp", "-r", src, dst], check=True, capture_output=True)


def _run_engine(src: str, dst: str, mode: CopyMode):
    done = threading.Event()
    errors = []

    def on_progress(p: CopyProgress):
        if p.finished or p.cancelled:
            if p.errors:
                errors.extend(p.errors)
            done.set()

    engine = CopyEngine()
    engine.start(CopyJob(sources=[src], destination=dst, mode=mode), on_progress)
    done.wait(timeout=600)
    if errors:
        raise RuntimeError(str(errors[0]))


def method_copysoft_auto(src, dst):   _run_engine(src, dst, CopyMode.AUTO)
def method_copysoft_large(src, dst):  _run_engine(src, dst, CopyMode.LARGE)
def method_copysoft_small(src, dst):  _run_engine(src, dst, CopyMode.SMALL)


# ──────────────────────────────────────────────────────────────────
# Benchmark runner
# ──────────────────────────────────────────────────────────────────

def run_method(
    name: str,
    fn: Callable,
    src_variants: List[Tuple[str, int]],
) -> dict:
    """
    Run fn(src, dst) for each variant (different src per run to dodge cache).
    Returns timing + speed stats.
    """
    times = []
    for run_idx, (src, total_bytes) in enumerate(src_variants):
        dst = os.path.join(DST_BASE, f"{name.replace(' ', '_')}_run{run_idx}")
        os.makedirs(dst, exist_ok=True)
        _clean_dst(dst)

        t0 = time.perf_counter()
        try:
            fn(src, dst)
        except Exception as e:
            print(f"\n    {RED}ERROR: {e}{RESET}")
            times.append(float("inf"))
            continue
        elapsed = time.perf_counter() - t0

        _clean_dst(dst)
        times.append(elapsed)

    valid = [t for t in times if t != float("inf")]
    if not valid:
        return {"name": name, "times": times, "median": float("inf"), "speed": 0, "total": 0}

    total_bytes = src_variants[0][1]
    median_t = statistics.median(valid)
    speed = total_bytes / median_t if median_t > 0 else 0

    return {
        "name":   name,
        "times":  valid,
        "median": median_t,
        "speed":  speed,
        "total":  total_bytes,
    }


def _clean_dst(dst: str):
    for item in os.listdir(dst):
        p = os.path.join(dst, item)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────

def print_results(case_name: str, total_bytes: int, results: list):
    print(f"\n{BOLD}{CYAN}{'─'*64}{RESET}")
    print(f"{BOLD}{CYAN}  {case_name}  ({_fmt_size(total_bytes)}){RESET}")
    print(f"{CYAN}{'─'*64}{RESET}")

    valid = [r for r in results if r["speed"] > 0]
    if not valid:
        print(f"  {RED}All methods failed.{RESET}")
        return

    best_speed   = max(r["speed"] for r in valid)
    shutil_speed = next((r["speed"] for r in results if r["name"] == "shutil"), None)

    print(f"  {DIM}{'Method':<26} {'Median speed':>13}  {'Time':>7}  {'vs shutil':>10}  {'Runs'}{RESET}")
    print(f"  {'─'*66}")

    for r in results:
        if r["speed"] == 0:
            print(f"  {RED}{r['name']:<26} {'ERROR':>13}{RESET}")
            continue

        is_best = abs(r["speed"] - best_speed) < 1

        vs = ""
        if shutil_speed and shutil_speed > 0 and r["name"] != "shutil":
            ratio = r["speed"] / shutil_speed
            sign  = "+" if ratio >= 1 else ""
            vs    = f"{sign}{(ratio-1)*100:.0f}%"

        speed_str = _fmt_size(int(r["speed"])) + "/s"
        time_str  = f"{r['median']:.2f}s"
        runs_str  = "  ".join(_fmt_size(int(r["total"] / t)) + "/s" for t in r["times"])
        marker    = f"  {BOLD}◀ BEST{RESET}" if is_best else ""

        if is_best:
            color = GREEN
        elif shutil_speed and r["speed"] > shutil_speed * 1.05:
            color = YELLOW
        elif shutil_speed and r["speed"] < shutil_speed * 0.95:
            color = DIM
        else:
            color = RESET

        print(f"  {color}{r['name']:<26} {speed_str:>13}  {time_str:>7}  {vs:>10}{RESET}{marker}")
        print(f"  {DIM}  runs: {runs_str}{RESET}")


# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────

def main():
    import platform as _pl
    print(f"\n{BOLD}{'='*64}")
    print(f"  CopySoft Benchmark v2 — {_pl.system()} {_pl.mac_ver()[0] or _pl.release()}")
    print(f"{'='*64}{RESET}")
    print(f"  Drive type : {CYAN}{get_drive_type(WORK_DIR)}{RESET}")
    print(f"  Python     : {sys.version.split()[0]}")
    print(f"  Runs/test  : {RUNS}  (different source file per run → avoids page-cache)")
    print(f"  Temp dir   : {DIM}{WORK_DIR}{RESET}\n")

    cases = create_test_files()

    scenarios = [
        {
            "name":     "A. Large file — 512 MB",
            "key":      "large_512mb",
            "methods": [
                ("shutil",          method_shutil),
                ("cp (native)",     method_cp),
                ("copysoft auto",   method_copysoft_auto),
                ("copysoft large",  method_copysoft_large),
            ],
        },
        {
            "name":     "B. Large file — 1 GB",
            "key":      "large_1gb",
            "methods": [
                ("shutil",          method_shutil),
                ("cp (native)",     method_cp),
                ("copysoft auto",   method_copysoft_auto),
                ("copysoft large",  method_copysoft_large),
            ],
        },
        {
            "name":     "C. Many files — 500 × 1 MB",
            "key":      "small_500x1mb",
            "methods": [
                ("shutil",          method_shutil),
                ("cp (native)",     method_cp),
                ("copysoft auto",   method_copysoft_auto),
                ("copysoft small",  method_copysoft_small),
            ],
        },
        {
            "name":     "D. Many files — 2000 × 256 KB",
            "key":      "small_2000x256kb",
            "methods": [
                ("shutil",          method_shutil),
                ("cp (native)",     method_cp),
                ("copysoft auto",   method_copysoft_auto),
                ("copysoft small",  method_copysoft_small),
            ],
        },
        {
            "name":     "E. Mixed — 50×5MB + 10×50MB",
            "key":      "mixed",
            "methods": [
                ("shutil",          method_shutil),
                ("cp (native)",     method_cp),
                ("copysoft auto",   method_copysoft_auto),
                ("copysoft small",  method_copysoft_small),
            ],
        },
    ]

    all_results = []

    for scenario in scenarios:
        variants = cases[scenario["key"]]
        total_bytes = variants[0][1]

        print(f"\n{BOLD}▶ Running: {scenario['name']}  ({_fmt_size(total_bytes)}){RESET}")
        results = []
        for method_name, fn in scenario["methods"]:
            print(f"  {DIM}  [{method_name:20s}]{RESET}", end=" ", flush=True)
            r = run_method(method_name, fn, variants)
            print(f"→ median {_fmt_size(int(r['speed']))+'/s':>11}" if r["speed"] else "→ ERROR")
            results.append(r)

        print_results(scenario["name"], total_bytes, results)
        all_results.append((scenario["name"], total_bytes, results))

    # ── Summary table ─────────────────────────────────────────────
    print(f"\n{BOLD}{CYAN}{'='*64}")
    print(f"  FINAL SUMMARY — CopySoft vs shutil (macOS Finder equivalent)")
    print(f"{'='*64}{RESET}")
    print(f"  {'Scenario':<34}  {'shutil':>10}  {'CopySoft best':>13}  {'Speedup':>8}")
    print(f"  {'─'*62}")

    for case_name, total, results in all_results:
        shutil_r = next((r for r in results if r["name"] == "shutil"), None)
        cs_res   = [r for r in results if r["name"].startswith("copysoft") and r["speed"] > 0]
        if not cs_res or not shutil_r or shutil_r["speed"] == 0:
            continue
        best_cs  = max(cs_res, key=lambda r: r["speed"])
        ratio    = best_cs["speed"] / shutil_r["speed"]
        color    = GREEN if ratio > 1.05 else (YELLOW if ratio >= 0.95 else RED)
        shutil_s = _fmt_size(int(shutil_r["speed"])) + "/s"
        best_s   = _fmt_size(int(best_cs["speed"])) + "/s"
        print(f"  {case_name:<34}  {shutil_s:>10}  {best_s:>13}  {color}{ratio:.2f}×  ({best_cs['name']}){RESET}")

    print()
    print(f"{DIM}Cleaning up {WORK_DIR}...{RESET}")
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    print(f"{GREEN}Done.{RESET}\n")


def _fmt_size(n: float) -> str:
    if n <= 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


if __name__ == "__main__":
    main()
