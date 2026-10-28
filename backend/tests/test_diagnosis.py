import json
import re
import sqlite3

import pytest

from postback_debugger import repository
from postback_debugger.data.models import FailureType
from postback_debugger.data.scenarios import SCENARIOS, SCENARIOS_BY_TYPE, Scenario
from postback_debugger.diagnosis import (
    SYSTEM_PROMPT,
    Diagnosis,
    build_click_context,
    build_diagnosis_prompt,
    diagnose_click,
    explain_postback,
)
from tests.conftest import FakeProvider


def _context(db: sqlite3.Connection, failure_type: FailureType):
    context = build_click_context(db, SCENARIOS_BY_TYPE[failure_type].click_id)
    assert context is not None
    return context


def test_unknown_click_has_no_context(db: sqlite3.Connection) -> None:
    assert build_click_context(db, "000000000000000000000000") is None


def test_context_includes_competing_click_and_its_partner(db: sqlite3.Connection) -> None:
    context = _context(db, FailureType.ATTRIBUTED_TO_OTHER_CLICK)
    (install,) = context.installs_on_device
    assert [c.click_id for c in context.other_clicks_on_device] == [install.click_id]
    assert {p.partner_id for p in context.partners} == {"alpha_ads", "gamma_network"}
    assert context.postback_logs == []


def test_context_includes_unsent_event_and_mapping(db: sqlite3.Connection) -> None:
    context = _context(db, FailureType.EVENT_NOT_MAPPED)
    assert "purchase_v2" in [e.event_name for e in context.events]
    (partner,) = context.partners
    assert "purchase_v2" not in partner.event_mapping


def test_context_for_click_without_install(db: sqlite3.Connection) -> None:
    context = _context(db, FailureType.NO_INSTALL)
    assert context.installs_on_device == [] and context.events == []


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.failure_type.value)
def test_prompt_contains_data_but_not_the_answer(
    db: sqlite3.Connection, scenario: Scenario
) -> None:
    context = build_click_context(db, scenario.click_id)
    assert context is not None
    prompt = build_diagnosis_prompt(context)

    match = re.search(r"<data>\n(.*)\n</data>", prompt, re.S)
    assert match is not None
    assert json.loads(match.group(1))["click"]["click_id"] == scenario.click_id
    assert scenario.description not in prompt
    assert "failure_type" not in prompt


def test_system_prompt_lists_every_failure_type() -> None:
    for failure_type in FailureType:
        assert f"- {failure_type.value}:" in SYSTEM_PROMPT


def test_diagnose_click_returns_validated_diagnosis(db: sqlite3.Connection) -> None:
    answer = Diagnosis(
        failure_type=FailureType.TIMEOUT, summary="s", evidence=["e"], recommended_fix="f"
    )
    provider = FakeProvider(answer=lambda prompt: answer)
    click_id = SCENARIOS_BY_TYPE[FailureType.TIMEOUT].click_id

    result = diagnose_click(provider, db, click_id)

    assert result.data == answer
    ((system, prompt),) = provider.calls
    assert system == SYSTEM_PROMPT
    assert click_id in prompt


def test_diagnose_unknown_click_raises(db: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown click_id"):
        diagnose_click(FakeProvider(), db, "000000000000000000000000")


def test_explain_postback_sends_the_log(db: sqlite3.Connection) -> None:
    log = repository.get_postback_log(db, "pb_000001")
    assert log is not None
    provider = FakeProvider(text="explained")

    result = explain_postback(provider, log)

    assert result.text == "explained"
    ((_, prompt),) = provider.calls
    assert log.postback_id in prompt and log.url in prompt


def test_partner_api_keys_are_redacted_everywhere(db: sqlite3.Connection) -> None:
    context = _context(db, FailureType.PARTNER_4XX)
    dumped = context.model_dump_json()
    assert "dk_test_7f3a9c51" not in dumped
    (partner,) = context.partners
    assert partner.api_key == "[redacted]"
    assert partner.api_key_expires_at is not None  # the clue the model needs stays
    assert all("key=[redacted]" in log.url for log in context.postback_logs)


def test_partners_without_keys_are_unchanged(db: sqlite3.Connection) -> None:
    context = _context(db, FailureType.TIMEOUT)
    assert context.partners[0].api_key is None
    assert "[redacted]" not in context.model_dump_json()
