"""Active experiments: the agent serves a deliberately mutated reconstruction to the ORIGINAL client.
SubQ picks which experiment to run next; the client's verdict turns a hypothesis into verified/refuted."""
from __future__ import annotations

from dataclasses import dataclass

from .journal import Entry
from .llm import ChoiceQ, ModelUnavailable, SubQ
from .oracle import OracleResult, probe
from .spec import ProtocolSpec
from .spec_server import MUTATIONS


@dataclass(frozen=True)
class Experiment:
    id: str
    mutation: str | None
    question: str
    if_fails: str
    if_passes: str
    script: tuple[str, ...] = ("status", "brightness=37", "color=12ab9f", "status")
    power_rule: str = "brightness_nonzero"


LIBRARY: tuple[Experiment, ...] = (
    Experiment("length_disambiguation", "seq_high",
               "Traffic fits BOTH 'length = u16 LE @6' and 'length = u16 BE @5' (seq never exceeded 255). Which is real?",
               "client rejects seq>255 frames: length is BE@5",
               "client accepts seq≥0x0101: length is u16 LE @6, BE@5 candidate refuted"),
    Experiment("client_checks_seq", "seq_frozen", "Does the client enforce server seq +1 per frame?",
               "client enforces server seq increments (must implement)", "client ignores server seq"),
    Experiment("client_checks_seq_start", "seq_start_random", "Must server seq start at 1?",
               "server seq must start at 1", "client accepts any initial server seq (start value is cosmetic)"),
    Experiment("client_checks_ack_seq", "ack_wrong_seq", "Does the client verify the ACK echoes the request seq?",
               "ACK must echo request seq (must implement)", "ACK seq echo is not checked"),
    Experiment("client_checks_ack_type", "ack_wrong_type", "Does the client verify the ACK echoes the request type?",
               "ACK must echo request type (must implement)", "ACK type echo is not checked by this client (implement anyway: observed in traffic)"),
    Experiment("client_checks_state", "status_stale", "Does the client cross-check STATUS against its own SETs?",
               "server must persist lamp state (must implement)", "client does not cross-check state"),
    Experiment("client_checks_auth_ok", "auth_ok_zero", "Does the client interpret AUTH_OK session/timestamp bytes?",
               "AUTH_OK contents are validated", "AUTH_OK contents are opaque to the client (any 6 bytes work)"),
    Experiment("client_checks_crc", "crc_swapped", "Does the client verify the checksum (and its byte order)?",
               "checksum is verified with exact byte order (must implement)", "checksum is not verified"),
    Experiment("oracle_manual_length", "doc_length_be", "Serve the manual's big-endian length to the real client",
               "real client rejects the manual's length encoding — manual is wrong", "manual's length encoding also works"),
    Experiment("oracle_manual_crc", "doc_crc_full", "Serve the manual's whole-frame CRC to the real client",
               "real client rejects the manual's CRC coverage — manual is wrong", "manual's CRC coverage also works"),
    Experiment("oracle_manual_ack", "doc_ack_0x80", "Serve the manual's ACK code 0x80 to the real client",
               "real client rejects ACK=0x80 — manual is wrong", "client accepts ACK=0x80"),
    Experiment("power_rule_constant_on", None, "Is STATUS byte 0 really tied to brightness? Serve 'always on' after brightness=0",
               "client rejects 'always on' after brightness=0: power = (brightness > 0) confirmed",
               "client accepts 'always on': power rule unconstrained",
               script=("brightness=0", "status"), power_rule="constant_on"),
)

assert all(e.mutation is None or e.mutation in MUTATIONS for e in LIBRARY)


def interpret(exp: Experiment, r: OracleResult) -> Entry:
    passed = r.ok
    verdict = exp.if_passes if passed else exp.if_fails
    return Entry(id=f"exp.{exp.id}", claim=f"🧪 {exp.question} → {verdict}" + ("" if passed else f" (client: “{r.error}”)"),
                 status="verified", confidence=1.0, source="oracle",
                 detail={"mutation": exp.mutation, "client_ok": passed, "client_error": r.error})


async def pick_next(remaining: list[Experiment], state: str, journal_text: str, subq: SubQ) -> tuple[Experiment, dict]:
    if len(remaining) == 1 or not subq.available:
        return remaining[0], {}
    q = ChoiceQ(instructions=("We are reconstructing a dead cloud server. Current hypothesis journal:\n" + journal_text
                              + "\nWhich client-oracle experiment should run NEXT to most reduce uncertainty about what "
                              "the replacement server must do? Prefer resolving ambiguous or contradicted facts first."),
                options={e.id: e.question for e in remaining})
    try:
        ans = (await subq.ask(state, {"next_experiment": q}))["next_experiment"]
    except ModelUnavailable:
        return remaining[0], {}
    chosen = next((e for e in remaining if e.id == ans.choice), remaining[0])
    return chosen, ans.probabilities or {}


async def run(exp: Experiment, spec: ProtocolSpec) -> OracleResult:
    muts = frozenset({exp.mutation}) if exp.mutation else frozenset()
    return await probe(spec, muts, exp.script, exp.power_rule)
