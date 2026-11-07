"""Hypothesis journal: append-only JSONL, every entry versioned, observed vs inferred kept separate.

status:
  verified — holds on every recorded packet (deterministic detector) or confirmed by the client oracle
  inferred — believed with probability `confidence` (SubQ) but not mechanically proven
  refuted  — contradicted by a counterexample (packet numbers / oracle run)
  open     — proposed, not yet assessed
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["verified", "inferred", "refuted", "open"]
Source = Literal["detector", "subq", "meta", "oracle", "manual"]

ICON = {"verified": "✅", "inferred": "🎲", "refuted": "❌", "open": "❓"}


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=80)
    claim: str = Field(min_length=1, max_length=600)
    status: Status
    confidence: float = Field(ge=0.0, le=1.0)
    source: Source
    evidence: tuple[int, ...] = ()
    detail: dict = Field(default_factory=dict)
    version: int = 1
    ts: float = Field(default_factory=time.time)

    def line(self) -> str:
        cites = ""
        if self.evidence:
            shown = ", ".join(f"#{i}" for i in self.evidence[:4])
            cites = f" [pkts {shown}{', …' if len(self.evidence) > 4 else ''}]"
        conf = f" p={self.confidence:.2f}" if self.status == "inferred" else ""
        return f"{ICON[self.status]} {self.claim}{conf}{cites} ({self.source})"


class Journal:
    def __init__(self, path: Path | None = None, on_change: Callable[[Entry], None] | None = None):
        self.path = path
        self._latest: dict[str, Entry] = {}
        self._on_change = on_change
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("")

    def record(self, entry: Entry) -> Entry:
        prev = self._latest.get(entry.id)
        stored = entry.model_copy(update={"version": prev.version + 1}) if prev else entry
        self._latest = {**self._latest, stored.id: stored}
        if self.path:
            with self.path.open("a") as fh:
                fh.write(stored.model_dump_json() + "\n")
        if self._on_change:
            self._on_change(stored)
        return stored

    def update(self, entry_id: str, **changes) -> Entry:
        return self.record(self._latest[entry_id].model_copy(update={**changes, "ts": time.time()}))

    def get(self, entry_id: str) -> Entry | None:
        return self._latest.get(entry_id)

    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._latest.values())

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in ICON}
        for e in self._latest.values():
            out = {**out, e.status: out[e.status] + 1}
        return out
