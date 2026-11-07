"""Map an ASI:One message (prose or card-selection JSON) to an agent intent."""
from __future__ import annotations

import json

INTENTS = {
    "resurrect": ("resurrect", "revive", "rebuild", "fix", "run", "bring", "start", "go"),
    "evidence": ("evidence", "traffic", "packets", "what do you have"),
    "journal": ("journal", "proof", "prove", "hypothes"),
    "lies": ("lie", "manual", "doc", "contradict"),
    "code": ("code", "server", "source", "download"),
}


def parse_intent(text: str) -> str:
    try:
        sel = json.loads(text)
        if isinstance(sel, dict) and sel.get("action") in INTENTS:
            return sel["action"]
    except (ValueError, TypeError):
        pass
    low = text.lower()
    for intent in ("journal", "lies", "code", "evidence", "resurrect"):
        if any(k in low for k in INTENTS[intent]):
            return intent
    return "hello"
