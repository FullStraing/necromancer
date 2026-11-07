"""Detectors are validated on a SYNTHETIC protocol unrelated to Lumio (different layout, CRC, endianness)."""
import random

import pytest

from necromancer import detectors as d
from necromancer.crc import BY_NAME, CATALOG
from necromancer.evidence import Packet

CHECK = {  # standard check values for b"123456789"
    "CRC-16/CCITT-FALSE": 0x29B1, "CRC-16/XMODEM": 0x31C3, "CRC-16/KERMIT": 0x2189, "CRC-16/AUG-CCITT": 0xE5CC,
    "CRC-16/MODBUS": 0x4B37, "CRC-16/ARC": 0xBB3D, "CRC-16/X-25": 0x906E, "CRC-16/BUYPASS": 0xFEE8,
}


@pytest.mark.parametrize("algo", CATALOG, ids=lambda a: a.name)
def test_crc_catalog_check_values(algo):
    assert algo.compute(b"123456789") == CHECK[algo.name]


def synth(n_sessions=6, seed=3):
    """Header: 'ZQ' | seq u16 BE @2 | type @4 | len u16 BE @5 | payload | XMODEM over [0:-2] BE."""
    rng = random.Random(seed)
    crc = BY_NAME["CRC-16/XMODEM"]
    pkts, idx = [], 0
    for s in range(1, n_sessions + 1):
        seqs = {"c2s": 254, "s2c": 254}
        for _ in range(rng.randint(2, 5)):
            for direction, t in (("c2s", rng.choice([1, 2, 3])), ("s2c", 0x40 | rng.choice([1, 2]))):
                body = b"ZQ" + seqs[direction].to_bytes(2, "big") + bytes([t])
                payload = rng.randbytes(rng.randint(0, 300))
                body += len(payload).to_bytes(2, "big") + payload
                idx += 1
                pkts.append(Packet(idx, s, float(idx), direction, body + crc.compute(body).to_bytes(2, "big")))
                seqs[direction] += 1
    return tuple(pkts)


def test_prefix_length_crc_on_synthetic():
    P = synth()
    assert d.constant_prefix(P).detail["bytes"] == b"ZQ".hex()
    lens = d.length_candidates(P)
    assert {"offset": 5, "endian": "big", "overhead": 9} in [f.detail for f in lens]
    c = d.checksum(P)
    assert c.detail == {"algo": "CRC-16/XMODEM", "start": 0, "endian": "big"}


def test_counter_and_type_on_synthetic():
    P = synth()
    seq = d.counter_field(P, skip={0, 1})
    assert seq.detail["offset"] == 2 and seq.detail["endian"] == "big" and seq.detail["start"] == 254
    t = d.type_field(P, skip={0, 1, 2, 3})
    assert t.detail["offset"] == 4


def test_length_detector_reports_ambiguity():
    """Small payloads + small seqs: a BE u16 straddling seq/len also fits. Detector must report both."""
    pkts = []
    for i in range(1, 6):
        payload = bytes(i)
        body = b"AB" + bytes([7]) + i.to_bytes(2, "little") + len(payload).to_bytes(2, "little") + payload
        pkts.append(Packet(i, 1, float(i), "c2s", body + b"\0\0"))
    offsets = {(f.detail["offset"], f.detail["endian"]) for f in d.length_candidates(tuple(pkts))}
    assert (5, "little") in offsets and (4, "big") in offsets


def test_counterexample_for_wrong_length():
    P = synth()
    assert d.counterexample_for_length(P, 5, "little", 9) is not None
    assert d.counterexample_for_length(P, 5, "big", 9) is None


def test_no_false_checksum_on_random_data():
    rng = random.Random(9)
    P = tuple(Packet(i, 1, 0.0, "c2s", rng.randbytes(20)) for i in range(1, 30))
    assert d.checksum(P) is None
