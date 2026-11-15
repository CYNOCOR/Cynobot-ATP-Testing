"""Start Cyno Control (python -m cyno.control).

On Windows the launcher and the Desktop shortcut use pythonw.exe, which has no console, so
a crash used to look like "nothing happened". Any failure to start is now written to
cyno-control-error.log in the project folder and, on Windows, shown in a message box that
names what is wrong (a missing package, usually after pulling new code without re-running
the setup).
"""

import importlib
import platform
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LOG = ROOT / "cyno-control-error.log"

# import name -> pip name, for what Cyno Control itself needs to open its window.
NEEDED = {"webview": "pywebview", "psutil": "psutil", "httpx": "httpx", "segno": "segno", "dotenv": "python-dotenv",
          "fastapi": "fastapi", "uvicorn": "uvicorn"}
FIX = "update-windows.bat" if platform.system() == "Windows" else "update-mac.sh"  # quick; setup-* is the full first-time install


def missing_packages() -> list[str]:
    out = []
    for module, pip_name in NEEDED.items():
        try:
            importlib.import_module(module)
        except Exception:  # not installed, or installed but broken
            out.append(pip_name)
    return out


def tell_user(title: str, message: str, detail: str = ""):
    """Write the full log, and show the short message where the user can see it."""
    try:
        LOG.write_text(f"{datetime.now():%Y-%m-%d %H:%M:%S}\n{title}\n\n{message}\n\n{detail}\n", encoding="utf-8")
    except OSError:
        pass
    print(f"{title}\n{message}\n{detail}", file=sys.stderr)
    if platform.system() == "Windows":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, f"{message}\n\nDetails: {LOG}", title, 0x10)  # 0x10 = error icon
        except Exception:
            pass


def run():
    missing = missing_packages()
    if missing:
        tell_user(
            "Cyno Control can't start",
            f"These Python packages are missing: {', '.join(missing)}.\n"
            f"Double-click {FIX} in the Cyno folder to install them (it is safe to run again), then open Cyno Control.",
        )
        return 1
    try:
        from cyno.control.app import main

        main()
    except Exception:
        detail = traceback.format_exc()
        hint = ""
        if platform.system() == "Windows" and ("WebView2" in detail or "clr" in detail or "pythonnet" in detail):
            hint = ("\nWindows needs the Microsoft Edge WebView2 Runtime to draw this window. "
                    f"Install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703, or run {FIX}.")
        tell_user("Cyno Control can't start", f"{detail.strip().splitlines()[-1]}{hint}", detail)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
