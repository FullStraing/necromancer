"""ASI:One Interactive Card builders (card_protocol_version 1) for the Necromancer agent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from uagents_core.contrib.protocols.chat import ChatMessage, MetadataContent, TextContent

REPO = "https://github.com/FullStraing/necromancer"
MAX_PAYLOAD = 60_000


def text_message(text: str, end: bool = False) -> ChatMessage:
    from uagents_core.contrib.protocols.chat import EndSessionContent
    content = [TextContent(type="text", text=text)]
    if end:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def card_message(narration: str, kind: str, payload: dict, terminal: bool = False) -> ChatMessage:
    body = json.dumps(payload)
    if len(body.encode()) > MAX_PAYLOAD:
        raise ValueError("card payload exceeds 64KB limit")
    meta = {"card_protocol_version": "1", "requires_card_interaction": "false" if terminal else "true",
            "card_kind": kind, "card_payload": body, "preferred_drawer_width_px": "560"}
    if terminal:
        meta["is_terminal"] = "true"
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
                       content=[TextContent(type="text", text=narration), MetadataContent(type="metadata", metadata=meta)])


def case_file(n_packets: int, n_sessions: int, cloud_status: str) -> dict:
    return {
        "title": "Case file: Lumio Smart Lamp (cloud shut down)",
        "summary_rows": [
            {"label": "Device", "value": "Lumio lamp — vendor bankrupt, cloud offline"},
            {"label": "Original app today", "value": cloud_status},
            {"label": "Evidence: traffic", "value": f"{n_packets} packets · {n_sessions} recorded sessions"},
            {"label": "Evidence: manual", "value": "partial developer doc (may be wrong)"},
            {"label": "Evidence: client", "value": "original app, bytecode only — used as black-box oracle"},
            {"label": "Ground truth", "value": "sealed (sha256 in ENVELOPE.sha256)"},
        ],
        "ctas": [
            {"label": "Resurrect the cloud", "selection": {"action": "resurrect"}, "primary": True},
            {"label": "Show the evidence", "selection": {"action": "evidence"}},
        ],
    }


def result_card(report) -> dict:
    c = report.journal.counts()
    synth = report.synth
    rows = [
        {"label": "Verdict", "value": "💡 Lamp resurrected" if synth and synth.passed == len(synth.results) else "⚠️ Partial"},
        {"label": "Original client vs new cloud", "value": f"{synth.passed}/{len(synth.results)} conformance scripts pass" if synth else "n/a"},
        {"label": "Server author", "value": f"{synth.author} ({synth.rounds} repair round(s))" if synth else "n/a"},
        {"label": "Journal", "value": f"✅ {c['verified']} verified · 🎲 {c['inferred']} inferred · ❌ {c['refuted']} refuted · ❓ {c['open']} open"},
        {"label": "Manual lies proven", "value": str(len(report.manual_lies))},
        {"label": "Oracle experiments", "value": str(len(report.experiments))},
        {"label": "Models", "value": f"SubQ {report.models.get('subq')} · Meta {report.models.get('meta')}"},
    ]
    return {
        "title": "Resurrection report",
        "summary_rows": rows,
        "ctas": [
            {"label": "Show proof journal", "selection": {"action": "journal"}, "primary": True},
            {"label": "Show manual lies", "selection": {"action": "lies"}},
            {"label": "Get server code", "selection": {"action": "code"}},
        ],
    }
