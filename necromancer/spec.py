"""Recovered protocol specification, derived mechanically from traffic by the detectors."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, Field

from . import detectors as d
from .evidence import Packet, sessions


class ProtocolSpec(BaseModel):
    prefix_hex: str
    header_len: int = Field(ge=4, le=16)
    type_off: int
    seq_off: int
    seq_endian: str
    seq_start: int
    len_off: int
    len_endian: str
    crc_algo: str
    crc_start: int
    crc_endian: str
    codes: dict[str, int]                 # role -> type code
    payload_sizes: dict[str, int]         # role -> fixed payload size (where constant)
    ack_seq_off: int = 0
    ack_type_off: int | None = None
    err_seq_off: int = 1
    auth_reverse: bool = False
    auth_xor: int = 0
    status_fields: dict[str, list[int]] = Field(default_factory=dict)   # name -> [offset, width]
    brightness_max: int = 255
    default_status_hex: str = ""


@dataclass(frozen=True)
class Derivation:
    spec: ProtocolSpec
    findings: tuple[d.Finding, ...]
    length_alternatives: tuple[d.Finding, ...]   # candidates the traffic cannot rule out


def _first_types(packets: tuple[Packet, ...], type_off: int, direction: str, position: int) -> int:
    counts = Counter()
    for pkts in sessions(packets).values():
        seq = [p for p in pkts if p.dir == direction]
        if len(seq) > position:
            counts[seq[position].data[type_off]] += 1
    return counts.most_common(1)[0][0]


def derive(packets: tuple[Packet, ...]) -> Derivation:
    prefix = d.constant_prefix(packets)
    crc = d.checksum(packets)
    if prefix is None or crc is None:
        raise ValueError("cannot frame the traffic: no constant prefix or checksum found")
    fixed = set(range(len(bytes.fromhex(prefix.detail["bytes"]))))
    tfield = d.type_field(packets, skip=fixed)
    seq = d.counter_field(packets, skip=fixed | {tfield.detail["offset"]})
    taken = fixed | {tfield.detail["offset"], seq.detail["offset"], seq.detail["offset"] + 1}
    lengths = d.length_candidates(packets)
    clean = [f for f in lengths if not {f.detail["offset"], f.detail["offset"] + 1} & taken]
    if not clean:
        raise ValueError("no length field candidate that is disjoint from other header fields")
    length = clean[0]
    header_len = max(taken | {length.detail["offset"] + 1}) + 1
    lay = d.Layout(header_len, tfield.detail["offset"], seq.detail["offset"], seq.detail["endian"],
                   length.detail["offset"], length.detail["endian"])

    t_off = lay.type_off
    hello = _first_types(packets, t_off, "c2s", 0)
    challenge = _first_types(packets, t_off, "s2c", 0)
    auth = _first_types(packets, t_off, "c2s", 1)
    auth_ok = _first_types(packets, t_off, "s2c", 1)
    cat = d.message_catalog(packets, lay)
    pairs = d.request_response(packets, lay)
    query = next(t for t, e in cat.items() if e["dir"] == "c2s" and set(e["sizes"]) == {0})
    status = pairs[query].most_common(1)[0][0]
    setters = [t for t, e in cat.items() if e["dir"] == "c2s" and t not in (hello, auth, query)]
    ack = Counter(pairs[s].most_common(1)[0][0] for s in setters).most_common(1)[0][0]
    error = next((t for s in setters for t in pairs[s] if t != ack), None)

    findings = [prefix, crc, tfield, seq, length]
    state = {s: d.state_echo(packets, lay, s, status, error if error is not None else -1) for s in setters}
    findings += [f for f in state.values() if f]
    width = {s: f.detail["width"] for s, f in state.items() if f}
    brightness = next((s for s in setters if width.get(s) == 1), setters[0])
    color = next((s for s in setters if width.get(s) == 3), setters[-1])
    echoes = d.echo_fields(packets, lay)
    findings += echoes
    auth_tf = d.challenge_transform(packets, lay, challenge, auth)
    if auth_tf:
        findings.append(auth_tf)
    rng = d.rejection_threshold(packets, lay, brightness, error) if error is not None else None
    if rng:
        findings.append(rng)

    def echo_off(rtype: int, what: str, default):
        return next((f.detail["offset"] for f in echoes if f.detail["type"] == rtype and f.detail["what"] == what), default)

    first_status = next(p for p in packets if p.data[t_off] == status)
    codes = {"hello": hello, "challenge": challenge, "auth": auth, "auth_ok": auth_ok, "get_status": query,
             "status": status, "set_brightness": brightness, "set_color": color, "ack": ack}
    if error is not None:
        codes["error"] = error
    sizes = {role: next(iter(cat[c]["sizes"])) for role, c in codes.items() if c in cat and len(cat[c]["sizes"]) == 1}
    status_fields = {("brightness" if s == brightness else "color"): [f.detail["offset"], f.detail["width"]]
                     for s, f in state.items() if f}
    spec = ProtocolSpec(
        prefix_hex=prefix.detail["bytes"], header_len=header_len, type_off=t_off,
        seq_off=lay.seq_off, seq_endian=lay.seq_endian, seq_start=seq.detail["start"],
        len_off=lay.len_off, len_endian=lay.len_endian,
        crc_algo=crc.detail["algo"], crc_start=crc.detail["start"], crc_endian=crc.detail["endian"],
        codes=codes, payload_sizes=sizes,
        ack_seq_off=echo_off(ack, "seq", 0), ack_type_off=echo_off(ack, "type", None),
        err_seq_off=echo_off(error, "seq", 1) if error is not None else 1,
        auth_reverse=bool(auth_tf and auth_tf.detail["reverse"]), auth_xor=auth_tf.detail["xor"] if auth_tf else 0,
        status_fields=status_fields, brightness_max=rng.detail["max_ok"] if rng else 255,
        default_status_hex=first_status.data[header_len:-2].hex(),
    )
    alternatives = tuple(f for f in lengths if f is not length)
    return Derivation(spec, tuple(findings), alternatives)
