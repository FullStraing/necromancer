"""Map an ASI:One message (prose or card-selection JSON) to an agent intent.

ASI:One may deliver a card click as raw selection JSON, as JSON prefixed by an @agent mention,
or as planner-written prose — so we look for an embedded {"action": ...} object first.
"""
from __future__ import annotations

import json
import re

INTENTS = {
    "resurrect": ("resurrect", "revive", "rebuild", "bring it back", "bring back", "fix it", "restore"),
    "evidence": ("evidence", "traffic", "packets", "what do you have"),
    "journal": ("journal", "proof", "hypothes"),
    "lies": ("lies", "lying", "manual", "contradict"),
    "code": ("code", "source", "download", "server.py"),
}
MENTION = re.compile(r"@agent1[0-9a-z]+")
JSON_OBJ = re.compile(r"\{[^{}]*\}")


def parse_intent(text: str) -> str:
    clean = MENTION.sub(" ", text or "")
    for blob in JSON_OBJ.findall(clean):
        try:
            sel = json.loads(blob)
        except ValueError:
            continue
        if isinstance(sel, dict) and sel.get("action") in INTENTS:
            return sel["action"]
    low = clean.lower()
    for intent in ("resurrect", "journal", "lies", "code", "evidence"):
        if any(k in low for k in INTENTS[intent]):
            return intent
    return "hello"
