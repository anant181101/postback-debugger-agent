"""Calls the real model. Skipped by default; run with:

uv run --env-file ../.env pytest -m live
"""

import sqlite3

import pytest

from postback_debugger.data.models import FailureType
from postback_debugger.data.scenarios import SCENARIOS_BY_TYPE
from postback_debugger.diagnosis import diagnose_click
from postback_debugger.llm import get_provider

pytestmark = pytest.mark.live


def test_real_model_diagnoses_a_timeout(db: sqlite3.Connection) -> None:
    scenario = SCENARIOS_BY_TYPE[FailureType.TIMEOUT]
    result = diagnose_click(get_provider(), db, scenario.click_id)
    assert result.data.failure_type is FailureType.TIMEOUT
    assert result.data.evidence
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
