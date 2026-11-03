"""Create .env from .env.example and ask for the Gemini key (hidden input). Used by the setup scripts."""

import getpass
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def main():
    if not ENV.exists():
        shutil.copy(ROOT / ".env.example", ENV)
    text = ENV.read_text(encoding="utf-8")
    if re.search(r"(?m)^GOOGLE_API_KEY=\S+", text):
        print("Gemini key already set in .env")
        return
    print("Get a free key at https://aistudio.google.com/apikey")
    try:
        key = getpass.getpass("Paste your Gemini API key (hidden; press Enter to skip = offline only): ").strip()
    except EOFError:  # no terminal attached (e.g. automated run)
        key = ""
    if not key:
        print("[!] No key: Cyno will run in OFFLINE mode only. Add it to .env later.")
        return
    line = f"GOOGLE_API_KEY={key}"
    if re.search(r"(?m)^GOOGLE_API_KEY=", text):
        text = re.sub(r"(?m)^GOOGLE_API_KEY=.*$", lambda _: line, text)
    else:
        text += f"\n{line}\n"
    ENV.write_text(text, encoding="utf-8")
    print("Saved to .env")


if __name__ == "__main__":
    main()
