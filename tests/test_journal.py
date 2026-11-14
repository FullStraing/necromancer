"""Entry rendering and journal counts — the proof journal is the demo's
evidence surface, so its formatting rules are pinned by tests."""
from necromancer.journal import Entry, Journal


def _entry(**over):
    base = dict(id="h1", claim="length is u16 LE @6", status="verified",
                confidence=1.0, source="detector")
    base.update(over)
    return Entry(**base)


def test_verified_line_has_no_probability():
    assert _entry().line() == "✅ length is u16 LE @6 (detector)"


def test_inferred_line_shows_probability():
    e = _entry(status="inferred", confidence=0.83, source="subq")
    assert e.line() == "🎲 length is u16 LE @6 p=0.83 (subq)"


def test_refuted_and_open_icons():
    assert _entry(status="refuted").line().startswith("❌ ")
    assert _entry(status="open").line().startswith("❓ ")


def test_evidence_citations_capped_at_four():
    e = _entry(evidence=(1, 2, 3, 4, 5, 6))
    assert e.line() == "✅ length is u16 LE @6 [pkts #1, #2, #3, #4, …] (detector)"
    e2 = _entry(evidence=(7, 8))
    assert e2.line() == "✅ length is u16 LE @6 [pkts #7, #8] (detector)"


def test_counts_per_status():
    j = Journal()
    j.record(_entry(id="a", status="verified"))
    j.record(_entry(id="b", status="inferred", confidence=0.7, source="subq"))
    j.record(_entry(id="c", status="refuted"))
    j.record(_entry(id="d", status="open"))
    assert j.counts() == {"verified": 1, "inferred": 1, "refuted": 1, "open": 1}
    # Updating an entry moves it between buckets; it is not double-counted.
    j.update("b", status="verified")
    assert j.counts() == {"verified": 2, "inferred": 0, "refuted": 1, "open": 1}
