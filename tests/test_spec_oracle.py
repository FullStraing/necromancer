import pytest

from necromancer.evidence import load_traffic, subsample
from necromancer.journal import Entry, Journal
from necromancer.oracle import probe
from necromancer.spec import derive


@pytest.fixture(scope="module")
def derivation():
    return derive(load_traffic())


def test_spec_recovers_layout(derivation):
    s = derivation.spec
    assert (s.type_off, s.seq_off, s.len_off, s.len_endian) == (3, 4, 6, "little")
    assert s.crc_algo == "CRC-16/CCITT-FALSE" and s.crc_start == 2
    assert s.auth_reverse and s.auth_xor == 0x5A
    assert s.brightness_max == 100


def test_ambiguous_length_candidate_is_kept(derivation):
    assert any(f.detail == {"offset": 5, "endian": "big", "overhead": 10} for f in derivation.length_alternatives)


async def test_original_client_accepts_recovered_spec(derivation):
    r = await probe(derivation.spec)
    assert r.ok, r.error


@pytest.mark.parametrize("mutation,expected_ok", [
    ("seq_frozen", False), ("ack_wrong_seq", False), ("status_stale", False),
    ("doc_ack_0x80", False), ("doc_length_be", False), ("doc_crc_full", False),
    ("auth_ok_zero", True), ("seq_high", True),
])
async def test_oracle_discriminates(derivation, mutation, expected_ok):
    assert (await probe(derivation.spec, frozenset({mutation}))).ok is expected_ok


def test_subsample_keeps_whole_sessions():
    P = load_traffic()
    small = subsample(P, 0.1)
    assert 0 < len(small) < len(P)
    assert {p.session for p in small} == {1, 2, 3}


def test_journal_versions_are_immutable(tmp_path):
    j = Journal(tmp_path / "j.jsonl")
    e = j.record(Entry(id="h1", claim="x", status="open", confidence=0.5, source="meta"))
    e2 = j.update("h1", status="inferred", confidence=0.9, source="subq")
    assert e.status == "open" and e2.version == 2 and j.get("h1").status == "inferred"
    assert len((tmp_path / "j.jsonl").read_text().splitlines()) == 2
    with pytest.raises(Exception):
        Entry(id="", claim="x", status="open", confidence=2, source="meta")
