"""Open the sealed envelope: verify hashes, then score the agent's recovered spec against ground truth.

Run: uv run python tools/reveal.py runs/<id>/spec.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def verify_envelope() -> bool:
    ok = True
    for line in (ROOT / "ENVELOPE.sha256").read_text().splitlines():
        digest, rel = line.split()
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        match = actual == digest
        ok &= match
        print(f"{'✅' if match else '❌'} {rel} sha256 {'matches' if match else 'MISMATCH'} the envelope")
    return ok


def flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        out.update(flatten(v, key + ".") if isinstance(v, dict) else {key: v})
    return out


def score(spec_path: Path) -> tuple[int, int]:
    truth = flatten(json.loads((ROOT / "sealed" / "truth.json").read_text())["spec"])
    got = flatten(json.loads(spec_path.read_text()))
    hits = 0
    for k, v in truth.items():
        match = got.get(k) == v
        hits += match
        print(f"{'✅' if match else '❌'} {k:28s} truth={v!r:24} agent={got.get(k)!r}")
    print(f"\nRecovered {hits}/{len(truth)} ground-truth fields exactly.")
    return hits, len(truth)


if __name__ == "__main__":
    if not verify_envelope():
        sys.exit("envelope mismatch — sealed files were modified")
    runs = sorted((ROOT / "runs").glob("*/spec.json"))
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (runs[-1] if runs else None)
    if target is None:
        sys.exit("no run found; run the pipeline first")
    score(target)
