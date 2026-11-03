"""Read and update .env in place, keeping comments and unknown lines."""

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

_LINE = re.compile(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*)=(.*)$")


def _ensure():
    if not ENV.exists():
        shutil.copy(EXAMPLE, ENV)


def read() -> dict[str, str]:
    """Active (uncommented) KEY=value pairs. Inline comments after values are stripped."""
    _ensure()
    values = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m and not m.group(1):
            values[m.group(2)] = m.group(3).split(" #")[0].strip()
    return values


def write(updates: dict[str, str | None]):
    """Set keys (None or "" comments the key out, so the default applies)."""
    _ensure()
    lines = ENV.read_text(encoding="utf-8").splitlines()
    pending = dict(updates)
    out = []
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(2) in pending:
            key, value = m.group(2), pending.pop(m.group(2))
            if value:
                out.append(f"{key}={value}")
            elif not m.group(1):  # was active, now cleared: comment it out to restore the default
                out.append(f"# {key}=")
            else:
                out.append(line)
        else:
            out.append(line)
    for key, value in pending.items():
        if value:
            out.append(f"{key}={value}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
