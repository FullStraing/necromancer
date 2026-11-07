import json

import pytest

from agent.cards import case_file, card_message
from agent.intents import parse_intent


@pytest.mark.parametrize("text,intent", [
    ('{"action": "resurrect"}', "resurrect"),
    ('{"action": "journal"}', "journal"),
    ("My Lumio lamp is bricked, can you bring it back?", "resurrect"),
    ("show me the proof journal", "journal"),
    ("where does the manual lie?", "lies"),
    ("give me the server code", "code"),
    ("hi", "hello"),
    ('{"action": "rm -rf"}', "hello"),
    ('@agent1qfnad6aftace8zyl0hh3xhzjh5m23hqlyl3mc9sgynz7644vttrc54n3csh {"action":"resurrect"}', "resurrect"),
    ('@agent1qfnad6aftace8zyl0hh3xhzjh5m23hqlyl3mc9sgynz7644vttrc54n3csh {"action":"journal"} proof', "journal"),
    ("The user clicked 'Resurrect the cloud' on the case file about the manual", "resurrect"),
])
def test_parse_intent(text, intent):
    assert parse_intent(text) == intent


def test_card_message_shape():
    msg = card_message("x", "detail", case_file(10, 2, "dead"))
    meta = msg.content[1].metadata
    assert meta["card_protocol_version"] == "1" and meta["card_kind"] == "detail"
    assert json.loads(meta["card_payload"])["ctas"][0]["selection"] == {"action": "resurrect"}
