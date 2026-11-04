"""Team-editable behaviour for Cyno (data/assistant.json), set from the Cyno Control app.

Read at the start of every conversation, so edits apply to the next visitor without a restart.
"""

import json
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "assistant.json"

DEFAULTS = {
    "greeting": "A visitor just walked up. Welcome them to IIT in one short sentence and ask how you can help.",
    "instructions": "",
    # Strict answers: only confirmed facts, no guessing, low creativity. On by default for demos.
    "strict": True,
    # Stay on topic: decline anything not about IIT or visiting the campus.
    "on_topic": False,
}

STRICT_RULES = """
Accuracy rules (strict mode, these override everything else):
- Only state facts that come from the knowledge you were given (the Facts list, including what
  your chest screen shows). Never use your own general knowledge about IIT or Cynocor, and never guess.
- Never invent or estimate names, room numbers, floors, directions, dates, times, prices, phone numbers,
  email addresses or web addresses. Say them exactly as they appear in the facts.
- If the information is missing, incomplete or the facts disagree with each other, say:
  "I'm not sure about that. Please check with the front desk." Do not try to fill the gap.
- If a visitor states something that conflicts with the facts, politely give the fact you have.
  Do not agree with information you cannot confirm.
"""

ON_TOPIC_RULES = """
Topic rule: only help with IIT and visiting the campus. For unrelated requests (homework, news, general
knowledge, other organisations), politely say you can only help with IIT questions.
"""

# Lower temperature = fewer creative (wrong) answers.
STRICT_TEMPERATURE = 0.2


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    out = {k: data.get(k, v) for k, v in DEFAULTS.items()}
    out["greeting"] = out["greeting"] or DEFAULTS["greeting"]
    return out


def save(greeting: str, instructions: str, strict: bool | None = None, on_topic: bool | None = None):
    current = load()
    current["greeting"] = greeting.strip() or DEFAULTS["greeting"]
    current["instructions"] = instructions.strip()
    if strict is not None:
        current["strict"] = bool(strict)
    if on_topic is not None:
        current["on_topic"] = bool(on_topic)
    PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def instructions_block() -> str:
    """Everything the team configured, appended to Cyno's system prompt."""
    cfg = load()
    parts = []
    if cfg["instructions"].strip():
        parts.append(f"\nExtra instructions from the IIT team (follow these too):\n{cfg['instructions'].strip()}\n")
    if cfg["on_topic"]:
        parts.append(ON_TOPIC_RULES)
    if cfg["strict"]:
        parts.append(STRICT_RULES)  # last, so it wins over anything above
    return "".join(parts)


def temperature() -> float | None:
    return STRICT_TEMPERATURE if load()["strict"] else None
