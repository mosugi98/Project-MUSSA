"""Build the portable MUSSA folder (no Python needed on the target PC).

    python tools/packaging/build_exe.py            # builds dist/MUSSA/MUSSA.exe and runs its self-test
    python tools/packaging/build_exe.py --zip      # also writes dist/MUSSA-<version>-portable.zip

Needs PyInstaller (pip install pyinstaller) and the app's own dependencies on THIS PC. The result holds no
patient data and no AI model: copy the four AI model files (segments and stenosis) to <data folder>\\models separately."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from cagsyntax import __version__  # noqa: E402

ZIP_NAME = f"MUSSA-{__version__}-portable.zip"
ENTRY = ROOT / "tools" / "packaging" / "mussa_entry.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

# Packages that load parts of themselves by name at run time, which PyInstaller cannot see.
COLLECT_ALL = ("pylibjpeg", "libjpeg", "onnxruntime")
COLLECT_DATA = ("pydicom",)
COLLECT_SUBMODULES = ("pydicom", "cagsyntax")
METADATA = ("pylibjpeg", "pylibjpeg-libjpeg", "pydicom", "numpy", "pillow", "onnxruntime")
EXCLUDES = ("tkinter", "pytest", "onnx", "matplotlib", "IPython", "unittest")


def pyinstaller_command() -> list[str]:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "MUSSA",
           "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD), "--paths", str(ROOT / "src")]
    for name in COLLECT_ALL:
        cmd += ["--collect-all", name]
    for name in COLLECT_DATA:
        cmd += ["--collect-data", name]
    for name in COLLECT_SUBMODULES:
        cmd += ["--collect-submodules", name]
    for name in METADATA:
        cmd += ["--copy-metadata", name]
    for name in EXCLUDES:
        cmd += ["--exclude-module", name]
    return cmd + [str(ENTRY)]


def selftest_exe(exe: Path) -> tuple[bool, str]:
    """Run the packaged exe's own self-test and return (passed, report text)."""
    report = exe.parent / "MUSSA-selftest.txt"
    report.unlink(missing_ok=True)
    done = subprocess.run([str(exe), "--selftest"], timeout=300)
    text = report.read_text(encoding="utf-8") if report.exists() else "(the exe wrote no report)"
    return done.returncode == 0 and "Self-test passed" in text, text


def write_readme(folder: Path) -> None:
    (folder / "READ ME FIRST.txt").write_text(
        f"MUSSA {__version__} - Mataram University Syntax Score Assistant\n"
        "Educational decision-support tool. Not a certified medical device.\n\n"
        "To start: double-click MUSSA.exe. Nothing needs to be installed.\n"
        "Windows may say 'Windows protected your PC' the first time (the program is not code-signed):\n"
        "click 'More info', then 'Run anyway'.\n\n"
        "Your data is kept in C:\\Users\\<your name>\\MUSSA-data (created on first start).\n"
        "AI (optional): copy segments.onnx, segments.card.json, stenosis.onnx and stenosis.card.json into\n"
        "C:\\Users\\<your name>\\MUSSA-data\\models\\ . Without them everything else still works.\n\n"
        "To check this copy works: run  MUSSA.exe --selftest  and read MUSSA-selftest.txt.\n"
        "Do not copy cases.sqlite or salt.key to another PC unless you mean to move your real cases;\n"
        "if you do, copy both together.\n", encoding="utf-8")


def make_zip(folder: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, Path("MUSSA") / path.relative_to(folder))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the portable MUSSA folder.")
    parser.add_argument("--zip", action="store_true", help=f"also write dist/{ZIP_NAME}")
    args = parser.parse_args()
    for folder in (DIST / "MUSSA", BUILD):
        shutil.rmtree(folder, ignore_errors=True)
    subprocess.run(pyinstaller_command(), cwd=ROOT, check=True)
    folder = DIST / "MUSSA"
    exe = folder / "MUSSA.exe"
    write_readme(folder)
    passed, report = selftest_exe(exe)
    print(report)
    if not passed:
        print("The packaged self-test FAILED: do not hand this build out.", file=sys.stderr)
        return 1
    size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file()) / 1e6
    print(f"Built {exe} ({size:.0f} MB, self-test passed)")
    if args.zip:
        target = DIST / ZIP_NAME
        make_zip(folder, target)
        print(f"Wrote {target} ({target.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
