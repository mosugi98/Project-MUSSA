# Install MUSSA on another PC

## The easy way: the portable folder

1. On the PC where MUSSA is already set up, build it (needs the project's Python environment once):

       python tools/packaging/build_exe.py --zip

   This writes `dist\MUSSA-2.0.0-portable.zip` (about 140 MB) and checks the packaged program before it finishes.
2. Copy `MUSSA-2.0.0-portable.zip` to the other PC (USB drive or a shared folder) and unzip it anywhere.
3. Double-click `MUSSA\MUSSA.exe`. Nothing else needs to be installed: no Python, no internet.
   Windows may say "Windows protected your PC" the first time because the program is not code-signed.
   Click **More info**, then **Run anyway**.

## What to copy, and what not to

| Item | Copy to the new PC? |
|---|---|
| `MUSSA-2.0.0-portable.zip` | Yes, that is the program |
| `segments.onnx` + `segments.card.json` | Optional, for AI segments. Put both in `C:\Users\<name>\MUSSA-data\models\` |
| `stenosis.onnx` + `stenosis.card.json` | Optional, for Suggest lesions. Same folder |
| `theme.json` | Optional, your saved look. Put it in `C:\Users\<name>\MUSSA-data\` |
| `cases.sqlite` + `salt.key` | Only if you mean to move your real cases. Copy both together, never one alone |
| DICOM images | No. Import them on the new PC from the original source |

A new PC starts with an empty data folder at `C:\Users\<name>\MUSSA-data`, created on first start.

## Check that a copy works

Run `MUSSA.exe --selftest` from a terminal in the MUSSA folder, or just open `MUSSA-selftest.txt` that it writes.
It lists nine checks (Qt, the two DICOM decoders, ONNX Runtime, Pillow, SQLite, the scoring engine and the two optional AI models) and ends
with "Self-test passed" when everything is fine.

## The other way: from the source code

Install Python 3.13, copy or clone the project, then in PowerShell:

    pip install pydicom numpy PySide6 pylibjpeg pylibjpeg-libjpeg pillow onnxruntime
    $env:PYTHONPATH = "src"
    python -m cagsyntax.selftest
    .\Run MUSSA.bat

## Updating

See `CHANGELOG.md` for what each version contains.
Build a new zip after the app changes and replace the MUSSA folder on the other PC. Your data lives in
`MUSSA-data`, outside that folder, so replacing the program keeps your cases.
