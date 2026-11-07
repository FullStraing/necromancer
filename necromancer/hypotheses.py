"""Semantic hypotheses: Meta proposes meanings for payload bytes; SubQ scores each one against the
FULL evidence dump (all packets + manual) in its long context. Result status = inferred, with p."""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from . import detectors as d
from .evidence import Packet
from .journal import Entry
from .llm import ChoiceQ, Meta, ModelUnavailable, NoulQ, SubQ
from .spec import ProtocolSpec


class SemanticHypothesis(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_\.]{3,60}$")
    message: str = Field(max_length=40)
    claim: str = Field(min_length=10, max_length=300)


class HypothesisSet(BaseModel):
    hypotheses: list[SemanticHypothesis] = Field(min_length=1, max_length=24)


FALLBACK = [
    SemanticHypothesis(id="hello.device_id", message="hello", claim="HELLO payload bytes 0-7 are a per-device identifier (the same lamp always sends the same 8 bytes)"),
    SemanticHypothesis(id="hello.firmware", message="hello", claim="HELLO payload bytes 8-9 are a little-endian firmware/app version number"),
    SemanticHypothesis(id="challenge.random", message="challenge", claim="CHALLENGE payload is a fresh random nonce, different in every session"),
    SemanticHypothesis(id="auth_ok.session_id", message="auth_ok", claim="AUTH_OK payload bytes 0-1 are a random session identifier"),
    SemanticHypothesis(id="auth_ok.timestamp", message="auth_ok", claim="AUTH_OK payload bytes 2-5 are a little-endian Unix timestamp (server clock)"),
    SemanticHypothesis(id="auth_ok.ttl", message="auth_ok", claim="AUTH_OK payload bytes 2-5 are a session time-to-live in seconds"),
    SemanticHypothesis(id="status.power", message="status", claim="STATUS byte 0 is a power flag: 1 when brightness > 0, else 0"),
    SemanticHypothesis(id="status.temperature", message="status", claim="STATUS byte 0 is the lamp temperature in °C"),
    SemanticHypothesis(id="error.code", message="error", claim="ERROR byte 0 is an error code; code 3 means 'value out of range'"),
    SemanticHypothesis(id="state.per_device", message="status", claim="The cloud stores lamp state per device id and it persists across sessions"),
]

SYSTEM = ("You are a senior protocol reverse-engineer. Given a partially recovered binary protocol, propose precise, "
          "falsifiable hypotheses about what the remaining payload bytes MEAN. Include plausible alternatives that "
          "compete with each other (so they can be scored). Never restate already-verified layout facts.")


def summarize_for_meta(spec: ProtocolSpec, packets: tuple[Packet, ...]) -> str:
    lay = d.Layout(spec.header_len, spec.type_off, spec.seq_off, spec.seq_endian, spec.len_off, spec.len_endian)
    names = {v: k for k, v in spec.codes.items()}
    samples: dict[str, list[str]] = {}
    for p in packets:
        role = names.get(p.data[spec.type_off], hex(p.data[spec.type_off]))
        if len(samples.setdefault(role, [])) < 5:
            samples[role].append(f"s{p.session}:{d.payload(p, lay).hex() or '(empty)'}")
    return ("Verified layout (from deterministic detectors):\n" + spec.model_dump_json(indent=1)
            + "\n\nPayload samples per message role:\n" + json.dumps(samples, indent=1))


async def propose(spec: ProtocolSpec, packets: tuple[Packet, ...], meta: Meta) -> tuple[list[SemanticHypothesis], str]:
    if meta.available:
        try:
            got = await meta.complete_json(SYSTEM, summarize_for_meta(spec, packets), HypothesisSet, max_tokens=3000)
            return _dedupe(got.hypotheses), "meta"
        except ModelUnavailable:
            pass
    return list(FALLBACK), "fallback-library"


def _dedupe(hs: list[SemanticHypothesis]) -> list[SemanticHypothesis]:
    seen, out = set(), []
    for h in hs:
        if h.id not in seen:
            seen.add(h.id)
            out.append(h)
    return out


async def score(hyps: list[SemanticHypothesis], state: str, subq: SubQ) -> list[Entry]:
    questions = {_qkey(h.id): NoulQ(
        instructions=f"Based on ALL recorded packets and the manual, is this hypothesis about the {h.message} message true? {h.claim}",
        true="The recorded bytes consistently support it and nothing contradicts it",
        false="Some recorded bytes contradict it, or a competing explanation fits better") for h in hyps}
    answers = await subq.ask(state, questions)
    return [Entry(id=f"sem.{h.id}", claim=h.claim, status="inferred", confidence=round(answers[_qkey(h.id)].noul or 0.0, 3),
                  source="subq", detail={"message": h.message}) for h in hyps]


POWER_RULES = {
    "brightness_nonzero": "Byte 0 of STATUS is 1 exactly when brightness > 0 (setting brightness 0 turns the lamp off)",
    "constant_on": "Byte 0 of STATUS is always 1 regardless of brightness",
    "independent": "Byte 0 is unrelated to brightness and set by some other command",
}


async def choose_power_rule(state: str, subq: SubQ) -> tuple[str, dict]:
    q = ChoiceQ(instructions="How does STATUS payload byte 0 behave in the recorded traffic?", options=POWER_RULES)
    ans = (await subq.ask(state, {"power_rule": q}))["power_rule"]
    return ans.choice or "brightness_nonzero", ans.probabilities or {}


def _qkey(hid: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", hid)[:60]
