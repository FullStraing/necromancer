"""Evidence loading and rendering — packet numbers are the citation
surface of the proof journal, so grouping, rendering and validation
are pinned by tests."""
import pytest
from pydantic import ValidationError

from necromancer.evidence import (
    Packet,
    TrafficRecord,
    load_traffic,
    render_state,
    sessions,
)


def _packet(idx, session=1, direction="c2s", data=b"\x01\x02"):
    return Packet(idx, session, 1.0 * idx, direction, data)


def test_sessions_groups_by_session_in_order():
    packets = (_packet(1, 1), _packet(2, 2), _packet(3, 1), _packet(4, 2))
    grouped = sessions(packets)
    assert list(grouped) == [1, 2]
    assert [p.idx for p in grouped[1]] == [1, 3]
    assert [p.idx for p in grouped[2]] == [2, 4]


def test_sessions_empty():
    assert sessions(()) == {}


def test_render_state_numbers_packets_and_shows_direction():
    packets = (_packet(1, 1, "c2s", b"\xaa\xbb"), _packet(2, 1, "s2c", b"\xcc"))
    text = render_state(packets, "MANUAL TEXT")
    assert "#1 s1 APP->CLOUD len=2 | aa bb" in text
    assert "#2 s1 CLOUD->APP len=1 | cc" in text
    assert "=== RECORDED TRAFFIC (packet#, session, direction, raw hex) ===" in text
    assert "=== RECOVERED VENDOR MANUAL (may contain errors) ===" in text
    assert "MANUAL TEXT" in text


def test_traffic_record_rejects_bad_hex():
    with pytest.raises(ValidationError):
        TrafficRecord(session=1, t=0.0, dir="c2s", hex="zz")


def test_traffic_record_rejects_bad_direction_and_session():
    with pytest.raises(ValidationError):
        TrafficRecord(session=1, t=0.0, dir="sideways", hex="00")
    with pytest.raises(ValidationError):
        TrafficRecord(session=-1, t=0.0, dir="c2s", hex="00")


def test_load_traffic_numbers_packets_from_one():
    packets = load_traffic()
    assert len(packets) == 246
    assert packets[0].idx == 1 and packets[-1].idx == 246
    assert all(p.data for p in packets)
    assert len(sessions(packets)) == 28
    assert sum(len(v) for v in sessions(packets).values()) == 246
    assert {p.dir for p in packets} == {"c2s", "s2c"}
