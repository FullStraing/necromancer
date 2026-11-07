"""Load recorded traffic into immutable, numbered packets (packet numbers are the evidence citations)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = ROOT / "evidence"


class TrafficRecord(BaseModel):
    session: int = Field(ge=0)
    t: float = Field(ge=0)
    dir: Literal["c2s", "s2c"]
    hex: str

    @field_validator("hex")
    @classmethod
    def _is_hex(cls, v: str) -> str:
        bytes.fromhex(v)
        return v


@dataclass(frozen=True)
class Packet:
    idx: int
    session: int
    t: float
    dir: str
    data: bytes


def load_traffic(path: Path | None = None) -> tuple[Packet, ...]:
    path = path or EVIDENCE_DIR / "traffic.jsonl"
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise RuntimeError(f"cannot read traffic capture {path}: {e}") from e
    records = [TrafficRecord.model_validate_json(line) for line in lines if line.strip()]
    return tuple(Packet(i + 1, r.session, r.t, r.dir, bytes.fromhex(r.hex)) for i, r in enumerate(records))


def load_manual(path: Path | None = None) -> str:
    return (path or EVIDENCE_DIR / "manual.md").read_text()


def sessions(packets: tuple[Packet, ...]) -> dict[int, tuple[Packet, ...]]:
    out: dict[int, list[Packet]] = {}
    for p in packets:
        out.setdefault(p.session, []).append(p)
    return {k: tuple(v) for k, v in out.items()}


def subsample(packets: tuple[Packet, ...], fraction: float) -> tuple[Packet, ...]:
    """Keep whole sessions (first N%) — used for the long-context ablation."""
    by_session = sessions(packets)
    keep = sorted(by_session)[: max(1, round(len(by_session) * fraction))]
    return tuple(p for s in keep for p in by_session[s])


def render_state(packets: tuple[Packet, ...], manual: str) -> str:
    """Plain-text evidence dump handed to SubQ as `state` (all packets, hex, numbered)."""
    rows = [f"#{p.idx} s{p.session} {'APP->CLOUD' if p.dir == 'c2s' else 'CLOUD->APP'} {p.data.hex()}" for p in packets]
    return ("=== RECORDED TRAFFIC (packet#, session, direction, raw hex) ===\n" + "\n".join(rows)
            + "\n\n=== RECOVERED VENDOR MANUAL (may contain errors) ===\n" + manual)
