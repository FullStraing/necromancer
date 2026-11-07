"""Necromancer pipeline: excavate → detect → cross-examine manual → hypothesize (Meta) → score (SubQ)
→ experiment on the original client (SubQ picks) → synthesize server (Meta) → prove with the original client."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from . import experiments as ex
from . import hypotheses as hy
from . import manual_check as mc
from .evidence import ROOT, load_manual, load_traffic, render_state, sessions
from .journal import Entry, Journal
from .llm import Meta, ModelUnavailable, SubQ
from .oracle import dead_cloud_check
from .spec import derive
from .synth import SynthResult, synthesize

Emit = Callable[[str, str], Awaitable[None]]


async def _noop(kind: str, text: str) -> None:
    return None


@dataclass
class Report:
    run_dir: Path
    journal: Journal
    synth: SynthResult | None = None
    manual_lies: list[Entry] = field(default_factory=list)
    experiments: list[Entry] = field(default_factory=list)
    models: dict = field(default_factory=dict)
    seconds: float = 0.0

    def summary(self) -> str:
        c = self.journal.counts()
        lines = [f"Journal: ✅ {c['verified']} verified · 🎲 {c['inferred']} inferred · ❌ {c['refuted']} refuted · ❓ {c['open']} open"]
        if self.synth:
            lines.append(f"Resurrected server ({self.synth.author}, {self.synth.rounds} Meta round(s)): original client passes "
                         f"{self.synth.passed}/{len(self.synth.results)} conformance scripts")
        lines.append(f"Manual contradictions proven: {len(self.manual_lies)} · Oracle experiments run: {len(self.experiments)}")
        lines.append(f"Models: {self.models} · {self.seconds:.0f}s")
        return "\n".join(lines)


def _journal_text(j: Journal, limit: int = 40) -> str:
    return "\n".join(e.line() for e in j.entries()[-limit:])


async def resurrect(emit: Emit = _noop, run_dir: Path | None = None, experiment_budget: int = 12,
                    subq: SubQ | None = None, meta: Meta | None = None) -> Report:
    t0 = time.time()
    run_dir = run_dir or ROOT / "runs" / time.strftime("%Y%m%d-%H%M%S")
    subq, meta = subq or SubQ(), meta or Meta()

    async def on_entry(e: Entry) -> None:
        await emit("entry", e.line())

    journal = Journal(run_dir / "journal.jsonl")
    record = journal.record

    async def rec(e: Entry) -> Entry:
        stored = record(e)
        await on_entry(stored)
        return stored

    report = Report(run_dir, journal, models={"subq": subq.model if subq.available else "unavailable",
                                              "meta": meta.model if meta.available else "unavailable"})

    await emit("stage", "1/7 Excavating evidence")
    packets, manual = load_traffic(), load_manual()
    dead = await dead_cloud_check()
    await rec(Entry(id="dead_cloud", claim=f"Original client today: “{dead.error}” — the lamp is bricked", status="verified",
                    confidence=1.0, source="oracle"))
    await emit("info", f"{len(packets)} packets in {len(sessions(packets))} sessions, manual {len(manual)} chars")
    state = render_state(packets, manual)

    await emit("stage", "2/7 Deterministic detectors (exhaustive search, zero counterexamples)")
    der = derive(packets)
    spec = der.spec
    for f in der.findings:
        await rec(Entry(id=f"det.{f.key}", claim=f.claim, status="verified", confidence=1.0, source="detector",
                        evidence=f.support[:6], detail=f.detail))
    for alt in der.length_alternatives:
        await rec(Entry(id=f"det.alt.{alt.key}", claim=f"AMBIGUOUS: traffic also fits {alt.claim}", status="open",
                        confidence=0.5, source="detector", evidence=alt.support[:3], detail=alt.detail))

    await emit("stage", "3/7 Cross-examining the vendor manual")
    claims, how = await mc.extract_claims(manual, meta)
    await emit("info", f"{len(claims)} checkable claims extracted ({how})")
    for c in claims:
        e = await rec(mc.check_claim(c, spec, packets, len(packets)))
        if e.status == "refuted":
            report.manual_lies.append(e)

    verified = "\n".join(f"- VERIFIED: {e.claim}" for e in journal.entries() if e.status == "verified")
    refuted = "\n".join(f"- REFUTED: {e.claim}" for e in journal.entries() if e.status == "refuted")
    state = state + "\n\n=== DETERMINISTIC DETECTOR RESULTS ===\n" + verified + "\n" + refuted

    await emit("stage", "4/7 Semantic hypotheses (Meta proposes, SubQ scores over the full evidence)")
    hyps, src = await hy.propose(spec, packets, meta)
    await emit("info", f"{len(hyps)} hypotheses from {src}")
    power_rule = "brightness_nonzero"
    if subq.available:
        try:
            for e in await hy.score(hyps, state, subq):
                await rec(e)
            power_rule, probs = await hy.choose_power_rule(state, subq)
            await rec(Entry(id="sem.power_rule", claim=f"SubQ: power rule = {power_rule}", status="inferred",
                            confidence=round(max(probs.values(), default=0.5), 3), source="subq",
                            detail={"probabilities": probs, "choice": power_rule}))
        except ModelUnavailable as err:
            await emit("warn", f"SubQ unavailable ({err}); hypotheses stay open")
            for h in hyps:
                await rec(Entry(id=f"sem.{h.id}", claim=h.claim, status="open", confidence=0.5, source="meta"))
    else:
        for h in hyps:
            await rec(Entry(id=f"sem.{h.id}", claim=h.claim, status="open", confidence=0.5, source="meta"))

    await emit("stage", "5/7 Active experiments on the ORIGINAL client (SubQ chooses the next one)")
    remaining = list(ex.LIBRARY)
    while remaining and len(report.experiments) < experiment_budget:
        exp, probs = await ex.pick_next(remaining, state, _journal_text(journal), subq)
        remaining = [e for e in remaining if e is not exp]
        if probs:
            await emit("info", f"SubQ picked “{exp.id}” (p={probs.get(exp.id, 0):.2f})")
        result = await ex.run(exp, spec)
        report.experiments.append(await rec(ex.interpret(exp, result)))
        if exp.id == "length_disambiguation" and result.ok:
            for alt in der.length_alternatives:
                await rec(journal.get(f"det.alt.{alt.key}").model_copy(update={
                    "status": "refuted", "source": "oracle", "confidence": 1.0,
                    "claim": f"{alt.claim} — refuted: client accepted frames with seq ≥ 0x0101"}))
        if exp.id == "power_rule_constant_on" and not result.ok:
            guess = journal.get("sem.power_rule")
            if guess and guess.detail.get("choice") != "brightness_nonzero":
                await rec(guess.model_copy(update={
                    "status": "refuted", "source": "oracle",
                    "claim": f"SubQ guessed power rule '{guess.detail.get('choice')}' (p={guess.confidence:.2f}) — "
                             f"REFUTED by the original client (“{result.error}”)"}))
            power_rule = "brightness_nonzero"
            await rec(Entry(id="oracle.power_rule", claim="power = (brightness > 0) — confirmed by the original client",
                            status="verified", confidence=1.0, source="oracle"))

    await emit("stage", "6/7 Writing the replacement cloud (Meta) and proving it with the original client")

    async def on_round(rnd: int, msg: str) -> None:
        await emit("info", msg)

    report.synth = await synthesize(spec, journal, power_rule, run_dir, meta, on_round=on_round)
    for sc, r in report.synth.results:
        await emit("check", f"{'✅' if r.ok else '❌'} client {' '.join(sc)} → {r.lamp if r.ok else r.error}")

    await emit("stage", "7/7 Done")
    report.seconds = time.time() - t0
    (run_dir / "spec.json").write_text(spec.model_dump_json(indent=2))
    (run_dir / "REPORT.md").write_text(render_markdown(report))
    return report


def render_markdown(r: Report) -> str:
    out = ["# Necromancer run report", "", "```", r.summary(), "```", "", "## Hypothesis journal", ""]
    out += [f"- {e.line()}" for e in r.journal.entries()]
    if r.synth:
        out += ["", "## Conformance (original client vs resurrected server)", ""]
        out += [f"- {'✅' if res.ok else '❌'} `{' '.join(sc)}` → {res.lamp if res.ok else res.error}" for sc, res in r.synth.results]
    return "\n".join(out) + "\n"
