"""Deterministic detectors. Each returns a Finding that holds for EVERY packet (verified) or None.

Detectors assume nothing about the layout: they search offsets, widths, endianness and CRC
parameters exhaustively and only report rules with zero counterexamples.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .crc import CATALOG, Crc16
from .evidence import Packet, sessions

MAX_HEADER = 8


@dataclass(frozen=True)
class Finding:
    key: str
    claim: str
    detail: dict
    support: tuple[int, ...] = field(default_factory=tuple)  # packet numbers proving it


def _u16(data: bytes, off: int, endian: str) -> int:
    return int.from_bytes(data[off:off + 2], endian)


def constant_prefix(packets: tuple[Packet, ...]) -> Finding | None:
    shortest = min(len(p.data) for p in packets)
    n = 0
    while n < shortest and len({p.data[n] for p in packets}) == 1:
        n += 1
    if n == 0:
        return None
    prefix = packets[0].data[:n]
    return Finding("prefix", f"every frame starts with constant bytes {prefix.hex()} ({prefix!r})",
                   {"offset": 0, "bytes": prefix.hex()}, tuple(p.idx for p in packets))


def length_candidates(packets: tuple[Packet, ...]) -> list[Finding]:
    """ALL (offset, endianness) pairs consistent with every packet — the evidence may be ambiguous."""
    out = []
    for off in range(MAX_HEADER - 1):
        for endian in ("little", "big"):
            overheads = {len(p.data) - _u16(p.data, off, endian) for p in packets}
            if len(overheads) == 1:
                ov = overheads.pop()
                out.append(Finding(f"length@{off}/{endian}", f"u16 {endian}-endian at offset {off} = frame length − {ov}",
                                   {"offset": off, "endian": endian, "overhead": ov}, tuple(p.idx for p in packets)))
    return out


def counterexample_for_length(packets: tuple[Packet, ...], off: int, endian: str, overhead: int) -> Packet | None:
    return next((p for p in packets if len(p.data) - _u16(p.data, off, endian) != overhead), None)


def checksum(packets: tuple[Packet, ...]) -> Finding | None:
    for algo in CATALOG:
        for start in range(MAX_HEADER):
            for endian in ("little", "big"):
                if all(_crc_ok(p.data, algo, start, endian) for p in packets):
                    return Finding("crc", f"{algo.name} over bytes [{start}:-2], stored {endian}-endian in last 2 bytes",
                                   {"algo": algo.name, "start": start, "endian": endian}, tuple(p.idx for p in packets))
    return None


def _crc_ok(data: bytes, algo: Crc16, start: int, endian: str) -> bool:
    return len(data) > start + 2 and algo.compute(data[start:-2]) == int.from_bytes(data[-2:], endian)


def crc_matches_anywhere(packets: tuple[Packet, ...], start: int) -> list[str]:
    """Which catalog CRCs (either endianness) explain ALL packets when coverage begins at `start`."""
    return [a.name for a in CATALOG for e in ("little", "big") if all(_crc_ok(p.data, a, start, e) for p in packets)]


def type_field(packets: tuple[Packet, ...], skip: set[int]) -> Finding | None:
    """Lowest offset (outside known fields) whose value partitions traffic by direction."""
    for off in range(MAX_HEADER):
        if off in skip:
            continue
        by_dir = {d: {p.data[off] for p in packets if p.dir == d} for d in ("c2s", "s2c")}
        if by_dir["c2s"] and by_dir["s2c"] and not (by_dir["c2s"] & by_dir["s2c"]) and len(by_dir["c2s"] | by_dir["s2c"]) <= 16:
            return Finding("type", f"byte {off} is a message-type code; app→cloud codes {sorted(hex(v) for v in by_dir['c2s'])}, "
                           f"cloud→app codes {sorted(hex(v) for v in by_dir['s2c'])} (never overlap)",
                           {"offset": off, "c2s": sorted(by_dir["c2s"]), "s2c": sorted(by_dir["s2c"])},
                           tuple(p.idx for p in packets))
    return None


def counter_field(packets: tuple[Packet, ...], skip: set[int]) -> Finding | None:
    by_session = sessions(packets)
    for off in range(MAX_HEADER - 1):
        if off in skip or off + 1 in skip:
            continue
        for endian in ("little", "big"):
            starts: set[int] = set()
            ok = True
            for pkts in by_session.values():
                for d in ("c2s", "s2c"):
                    vals = [_u16(p.data, off, endian) for p in pkts if p.dir == d]
                    if not vals:
                        continue
                    starts.add(vals[0])
                    if any(b - a != 1 for a, b in zip(vals, vals[1:])):
                        ok = False
                        break
                if not ok:
                    break
            if ok and len(starts) == 1:
                return Finding("seq", f"u16 {endian}-endian at offset {off} is a per-direction counter starting at {starts.pop()}, +1 per frame",
                               {"offset": off, "endian": endian, "start": min(starts) if starts else 1},
                               tuple(p.idx for p in packets))
    return None


@dataclass(frozen=True)
class Layout:
    header_len: int
    type_off: int
    seq_off: int
    seq_endian: str
    len_off: int
    len_endian: str


def payload(p: Packet, lay: Layout) -> bytes:
    return p.data[lay.header_len:-2]


def message_catalog(packets: tuple[Packet, ...], lay: Layout) -> dict[int, dict]:
    cat: dict[int, dict] = {}
    for p in packets:
        t = p.data[lay.type_off]
        entry = cat.setdefault(t, {"dir": p.dir, "sizes": Counter(), "packets": []})
        entry["sizes"][len(payload(p, lay))] += 1
        entry["packets"].append(p.idx)
    return cat


def request_response(packets: tuple[Packet, ...], lay: Layout) -> dict[int, Counter]:
    pairs: dict[int, Counter] = defaultdict(Counter)
    for pkts in sessions(packets).values():
        for req, resp in zip(pkts, pkts[1:]):
            if req.dir == "c2s" and resp.dir == "s2c":
                pairs[req.data[lay.type_off]][resp.data[lay.type_off]] += 1
    return dict(pairs)


def echo_fields(packets: tuple[Packet, ...], lay: Layout) -> list[Finding]:
    """Fields in a response payload that always equal the request's seq or type."""
    found = []
    by_resp: dict[int, list[tuple[Packet, Packet]]] = defaultdict(list)
    for pkts in sessions(packets).values():
        for req, resp in zip(pkts, pkts[1:]):
            if req.dir == "c2s" and resp.dir == "s2c":
                by_resp[resp.data[lay.type_off]].append((req, resp))
    for rtype, pairs in sorted(by_resp.items()):
        n = min(len(payload(r, lay)) for _, r in pairs)
        for off in range(n):
            if off + 2 <= n and all(payload(r, lay)[off:off + 2] == q.data[lay.seq_off:lay.seq_off + 2] for q, r in pairs):
                found.append(Finding(f"echo_seq_{rtype:02x}", f"type 0x{rtype:02x} payload[{off}:{off + 2}] echoes the request's seq",
                                     {"type": rtype, "offset": off, "what": "seq"}, tuple(r.idx for _, r in pairs)))
            if all(payload(r, lay)[off] == q.data[lay.type_off] for q, r in pairs) and len({q.data[lay.type_off] for q, _ in pairs}) > 1:
                found.append(Finding(f"echo_type_{rtype:02x}", f"type 0x{rtype:02x} payload[{off}] echoes the request's type code",
                                     {"type": rtype, "offset": off, "what": "type"}, tuple(r.idx for _, r in pairs)))
    return found


def challenge_transform(packets: tuple[Packet, ...], lay: Layout, ch_type: int, resp_type: int) -> Finding | None:
    """Search simple transforms f with AUTH.payload == f(CHALLENGE.payload) across all handshakes."""
    pairs = []
    for pkts in sessions(packets).values():
        for a, b in zip(pkts, pkts[1:]):
            if a.data[lay.type_off] == ch_type and b.data[lay.type_off] == resp_type:
                pairs.append((a, b))
    if not pairs:
        return None
    for reverse in (False, True):
        for xor in range(256):
            def f(n: bytes) -> bytes:
                src = n[::-1] if reverse else n
                return bytes(x ^ xor for x in src)
            if all(f(payload(a, lay)) == payload(b, lay) for a, b in pairs):
                desc = f"{'reversed ' if reverse else ''}nonce XOR 0x{xor:02x}"
                return Finding("auth", f"AUTH response = {desc} (holds for all {len(pairs)} handshakes)",
                               {"reverse": reverse, "xor": xor}, tuple(b.idx for _, b in pairs))
    return None


def state_echo(packets: tuple[Packet, ...], lay: Layout, set_type: int, status_type: int, err_type: int) -> Finding | None:
    """Offset in STATUS payload that reflects the last value written by `set_type` in the same session."""
    obs = []
    for pkts in sessions(packets).values():
        last = None
        for i, p in enumerate(pkts):
            t = p.data[lay.type_off]
            nxt = pkts[i + 1] if i + 1 < len(pkts) else None
            accepted = nxt is not None and nxt.dir == "s2c" and nxt.data[lay.type_off] != err_type
            if t == set_type and accepted:
                last = payload(p, lay)
            elif t == status_type and last is not None:
                obs.append((last, p))
    if not obs:
        return None
    k = len(obs[0][0])
    for off in range(len(payload(obs[0][1], lay)) - k + 1):
        if all(payload(s, lay)[off:off + k] == v for v, s in obs):
            return Finding(f"state_{set_type:02x}", f"STATUS payload[{off}:{off + k}] reflects the last accepted 0x{set_type:02x} value",
                           {"set_type": set_type, "offset": off, "width": k}, tuple(s.idx for _, s in obs))
    return None


def rejection_threshold(packets: tuple[Packet, ...], lay: Layout, set_type: int, err_type: int) -> Finding | None:
    accepted, rejected = [], []
    for pkts in sessions(packets).values():
        for a, b in zip(pkts, pkts[1:]):
            if a.data[lay.type_off] == set_type and b.dir == "s2c":
                (rejected if b.data[lay.type_off] == err_type else accepted).append((payload(a, lay)[0], b.idx))
    if not accepted or not rejected:
        return None
    hi_ok, lo_bad = max(v for v, _ in accepted), min(v for v, _ in rejected)
    if hi_ok >= lo_bad:
        return None
    return Finding(f"range_{set_type:02x}", f"0x{set_type:02x} values ≤ {hi_ok} accepted, ≥ {lo_bad} rejected with 0x{err_type:02x}",
                   {"max_ok": hi_ok, "min_bad": lo_bad}, tuple(i for _, i in rejected))
