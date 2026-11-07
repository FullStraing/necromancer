"""Long-context ablation for SubQ: the SAME typed questions, answered with the full evidence vs. a slice.

The manual (which contains planted errors) is always included, so with little traffic the model is tempted
to trust the manual; with the full capture in context it should override it.
Scored against the sealed answer key (sealed/truth.json), available only to the person running the reveal.

Run: uv run python -m necromancer.ablation
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .evidence import ROOT, load_manual, load_traffic, render_state, subsample
from .llm import ChoiceQ, SubQ

ROLES = {"magic": "constant frame marker", "protocol_version": "protocol version number", "message_type": "message type code",
         "sequence_counter": "per-direction sequence counter", "payload_length": "payload length",
         "checksum": "checksum over the frame", "payload": "message-specific payload data"}
CODES = {"x80": "0x80", "x90": "0x90", "xee": "0xEE", "x83": "0x83"}

QUESTIONS: dict[str, ChoiceQ] = {
    "bytes_0_1": ChoiceQ(instructions="What are bytes 0-1 of every frame?", options=ROLES),
    "byte_2": ChoiceQ(instructions="What is byte 2 of every frame?", options=ROLES),
    "byte_3": ChoiceQ(instructions="What is byte 3 of every frame?", options=ROLES),
    "bytes_4_5": ChoiceQ(instructions="What are bytes 4-5 of every frame?", options=ROLES),
    "bytes_6_7": ChoiceQ(instructions="What are bytes 6-7 of every frame?", options=ROLES),
    "last_2": ChoiceQ(instructions="What are the last 2 bytes of every frame?", options=ROLES),
    "length_endianness": ChoiceQ(instructions="What is the byte order of the payload-length field?",
                                 options={"little": "little-endian", "big": "big-endian"}),
    "crc_coverage": ChoiceQ(instructions="Which bytes does the frame checksum cover?",
                            options={"entire_frame": "from byte 0 (incl. the magic) through the payload",
                                     "from_byte_2": "from byte 2 (after the magic) through the payload",
                                     "from_byte_3": "from byte 3 through the payload", "payload_only": "payload only"}),
    "ack_code": ChoiceQ(instructions="Which type code does the cloud use to acknowledge SET commands?", options=CODES),
    "error_code": ChoiceQ(instructions="Which type code does the cloud use to reject a command?", options=CODES),
    "auth_relation": ChoiceQ(instructions="How is the AUTH payload derived from the preceding CHALLENGE nonce?",
                             options={"copied": "identical to the nonce", "reversed_xor_5a": "nonce bytes reversed, each XOR 0x5A",
                                      "xor_5a": "each nonce byte XOR 0x5A (same order)", "plus_one": "nonce + 1",
                                      "unrelated": "unrelated / cryptographic hash"}),
    "status_byte_0": ChoiceQ(instructions="What does STATUS payload byte 0 mean?",
                             options={"power": "power on/off flag", "brightness": "brightness", "red": "red channel", "temperature": "temperature"}),
    "status_byte_1": ChoiceQ(instructions="What does STATUS payload byte 1 mean?",
                             options={"power": "power on/off flag", "brightness": "brightness", "red": "red channel", "temperature": "temperature"}),
    "brightness_max": ChoiceQ(instructions="What is the largest brightness value the cloud accepts?",
                              options={"v100": "100", "v127": "127", "v255": "255"}),
    "seq_start": ChoiceQ(instructions="What value does the sequence counter take on the first frame of a session?",
                         options={"zero": "0", "one": "1", "random": "random"}),
    "ack_payload": ChoiceQ(instructions="What is in the 3-byte ACK payload?",
                           options={"seq_then_type": "request seq (u16 LE) then request type", "type_then_seq": "request type then request seq",
                                    "seq_only": "request seq and a padding byte", "crc": "checksum of the request"}),
    "error_payload": ChoiceQ(instructions="What is in the 3-byte error payload?",
                             options={"code_then_seq": "error code then request seq (u16 LE)", "seq_then_code": "request seq then error code",
                                      "code_only": "error code and padding"}),
    "manual_reliable": ChoiceQ(instructions="Is the vendor manual fully consistent with the recorded traffic?",
                               options={"yes": "every checkable statement matches the traffic", "no": "at least one statement contradicts the traffic"}),
}

FRACTIONS = {"full (28 sessions)": 1.0, "25%": 0.25, "10%": 0.1, "manual only": 0.0}


async def run_ablation(truth_path: Path = ROOT / "sealed" / "truth.json", out: Path = ROOT / "results" / "ablation.json") -> dict:
    subq = SubQ()
    truth = json.loads(truth_path.read_text())["ablation"]
    packets, manual = load_traffic(), load_manual()
    results = {}
    for label, frac in FRACTIONS.items():
        pk = subsample(packets, frac) if frac > 0 else ()
        state = render_state(pk, manual)
        answers = await subq.ask(state, QUESTIONS)
        rows = {q: {"choice": a.choice, "p_true": round((a.probabilities or {}).get(truth[q], 0.0), 3), "correct": a.choice == truth[q]}
                for q, a in answers.items()}
        acc = sum(r["correct"] for r in rows.values()) / len(rows)
        results[label] = {"packets": len(pk), "accuracy": round(acc, 3),
                          "mean_p_true": round(sum(r["p_true"] for r in rows.values()) / len(rows), 3), "answers": rows}
        print(f"{label:>20}: {len(pk):4d} packets  accuracy {acc:.0%}  mean p(true) {results[label]['mean_p_true']:.2f}")
    results["_meta"] = {"model": subq.model, "input_tokens": subq.input_tokens, "questions": len(QUESTIONS)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    asyncio.run(run_ablation())
