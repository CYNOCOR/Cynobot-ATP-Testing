"""Give Cyno Control a branded launcher. Run by the setup scripts; safe to re-run.

macOS:   puts the Cynocor icon on 'Cyno Control.command' in Finder.
Windows: creates a 'Cyno Control' shortcut on the Desktop with the Cynocor icon.

    python -m cyno.control.install_icons
"""

import os
import platform
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ASSETS = HERE / "assets"


def mac():
    from AppKit import NSImage, NSWorkspace

    target = ROOT / "Cyno Control.command"
    image = NSImage.alloc().initWithContentsOfFile_(str(ASSETS / "cyno-control-icon.png"))
    ok = NSWorkspace.sharedWorkspace().setIcon_forFile_options_(image, str(target), 0)
    print(f"[{'ok' if ok else '!!'}] Finder icon on {target.name}")


def windows():
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    shortcut = desktop / "Cyno Control.lnk"
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CYNO_LNK); "
        "$s.TargetPath = $env:CYNO_PYW; $s.Arguments = '-m cyno.control'; "
        "$s.WorkingDirectory = $env:CYNO_ROOT; $s.IconLocation = $env:CYNO_ICO; "
        "$s.Description = 'Cyno Control by Cynocor'; $s.Save()"
    )
    env = {**os.environ, "CYNO_LNK": str(shortcut), "CYNO_PYW": str(pythonw), "CYNO_ROOT": str(ROOT),
           "CYNO_ICO": str(ASSETS / "cyno-control-icon.ico")}
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True)
    print(f"[ok] Desktop shortcut: {shortcut}")


if __name__ == "__main__":
    system = platform.system()
    try:
        if system == "Darwin":
            mac()
        elif system == "Windows":
            windows()
    except Exception as e:  # cosmetic; never fail setup over an icon
        print(f"[!!] Could not set the launcher icon: {e}")
