"""Entry point of the packaged MUSSA.exe.

    MUSSA.exe              starts the app
    MUSSA.exe --selftest   checks the install (no window); writes MUSSA-selftest.txt beside the exe

The exe has no console window, so the self-test report goes to a file as well as to the console if there is one."""
import sys
from pathlib import Path


def run_selftest() -> int:
    from cagsyntax import selftest
    results = selftest.run_selftest()
    from cagsyntax import __version__
    report = f"MUSSA {__version__}" + chr(10) + chr(10) + selftest.format_report(results)
    folder = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    try:
        (folder / "MUSSA-selftest.txt").write_text(report, encoding="utf-8")
    except OSError:
        pass
    if sys.stdout is not None:
        print(report)
    return 1 if any(not r.ok for r in results) else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(run_selftest())
    from cagsyntax.app import main
    main()
