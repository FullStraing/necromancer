"""Experiment library invariants — every experiment must point at a real
mutation (or none), and the verdict mapping must read the oracle result."""
from necromancer.experiments import LIBRARY, interpret
from necromancer.oracle import OracleResult
from necromancer.spec_server import MUTATIONS


def test_library_ids_unique():
    ids = [e.id for e in LIBRARY]
    assert len(ids) == len(set(ids))


def test_library_mutations_exist():
    for exp in LIBRARY:
        assert exp.mutation is None or exp.mutation in MUTATIONS


def test_library_questions_verdicts_and_scripts_present():
    for exp in LIBRARY:
        assert exp.question and exp.if_fails and exp.if_passes
        assert exp.question != exp.if_fails
        assert exp.if_fails != exp.if_passes
        assert exp.script  # the client commands the experiment runs
        assert exp.power_rule in ("brightness_nonzero", "constant_on")


def test_interpret_pass_uses_if_passes():
    exp = LIBRARY[0]
    entry = interpret(exp, OracleResult(True, None))
    assert entry.id == f"exp.{exp.id}"
    assert entry.status == "verified"
    assert exp.if_passes in entry.claim
    assert entry.detail["mutation"] == exp.mutation
    assert entry.detail["client_ok"] is True


def test_interpret_fail_uses_if_fails_and_client_error():
    exp = LIBRARY[0]
    entry = interpret(exp, OracleResult(False, "client rejected the frame"))
    assert exp.if_fails in entry.claim
    assert "client rejected the frame" in entry.claim
    assert entry.detail["client_ok"] is False
    assert entry.detail["client_error"] == "client rejected the frame"
