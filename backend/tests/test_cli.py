from pathlib import Path

import pytest

from postback_debugger import cli
from postback_debugger.data.models import FailureType
from postback_debugger.data.scenarios import SCENARIOS, SCENARIOS_BY_TYPE
from postback_debugger.diagnosis import Diagnosis
from postback_debugger.llm import LLMError, QuotaExceededError
from tests.conftest import FakeProvider, click_id_in

EXPECTED = {s.click_id: s.failure_type for s in SCENARIOS}


def _answer_from_ground_truth(prompt: str) -> Diagnosis:
    return Diagnosis(
        failure_type=EXPECTED[click_id_in(prompt)],
        summary="summary",
        evidence=["evidence one"],
        recommended_fix="fix",
    )


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider(answer=_answer_from_ground_truth, text="It timed out.")
    monkeypatch.setattr(cli, "get_provider", lambda name, model: provider)
    return provider


def test_diagnose_one_prints_the_diagnosis(
    fake: FakeProvider, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    click_id = SCENARIOS_BY_TYPE[FailureType.TIMEOUT].click_id
    assert cli.main(["--db", str(db_file), "diagnose", click_id]) == 0
    out = capsys.readouterr().out
    assert f"Click {click_id}  ->  timeout" in out
    assert "  - evidence one" in out
    assert "100 in / 50 out (thinking 20)" in out and "$0.0010" in out


def test_diagnose_all_scores_every_scenario(
    fake: FakeProvider, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--db", str(db_file), "diagnose", "--all"]) == 0
    out = capsys.readouterr().out
    assert f"Score {len(SCENARIOS)}/{len(SCENARIOS)}" in out
    assert len(fake.calls) == len(SCENARIOS)


def test_diagnose_all_reports_wrong_answers_and_errors(
    monkeypatch: pytest.MonkeyPatch, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    timeout_click = SCENARIOS_BY_TYPE[FailureType.TIMEOUT].click_id
    none_click = SCENARIOS_BY_TYPE[FailureType.NONE].click_id

    def answer(prompt: str) -> Diagnosis:
        click_id = click_id_in(prompt)
        if click_id == timeout_click:
            raise LLMError("model overloaded")
        wrong = FailureType.DUPLICATE if click_id == none_click else EXPECTED[click_id]
        return Diagnosis(failure_type=wrong, summary="s", evidence=[], recommended_fix="f")

    monkeypatch.setattr(cli, "get_provider", lambda name, model: FakeProvider(answer=answer))
    assert cli.main(["--db", str(db_file), "diagnose", "--all"]) == 1
    out = capsys.readouterr().out
    assert f"Score {len(SCENARIOS) - 2}/{len(SCENARIOS)}" in out
    assert "ERROR: model overloaded" in out
    assert "✗" in out


def test_explain_prints_text(
    fake: FakeProvider, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--db", str(db_file), "explain", "pb_000001"]) == 0
    assert "It timed out." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["diagnose", "clk_00000000"], "Unknown click_id"),
        (["explain", "pb_missing"], "Unknown postback_id"),
    ],
)
def test_unknown_ids(
    fake: FakeProvider,
    db_file: Path,
    capsys: pytest.CaptureFixture[str],
    args: list[str],
    message: str,
) -> None:
    assert cli.main(["--db", str(db_file), *args]) == 1
    assert message in capsys.readouterr().out
    assert fake.calls == []  # no model call for an unknown id


def test_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--db", str(tmp_path / "none.db"), "diagnose", "--all"]) == 1
    assert "uv run seed-db" in capsys.readouterr().out


def test_provider_errors_are_printed(
    monkeypatch: pytest.MonkeyPatch, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(name: str | None, model: str | None) -> FakeProvider:
        raise LLMError("Gemini client not configured")

    monkeypatch.setattr(cli, "get_provider", broken)
    assert cli.main(["--db", str(db_file), "diagnose", "--all"]) == 1
    assert "Error: Gemini client not configured" in capsys.readouterr().out


def test_unreadable_database_is_reported(
    fake: FakeProvider, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")  # exists, but has no tables
    assert cli.main(["--db", str(empty), "diagnose", "clk_00000000"]) == 1
    assert "Database error" in capsys.readouterr().out


def test_diagnose_all_stops_when_quota_is_exhausted(
    monkeypatch: pytest.MonkeyPatch, db_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def answer(prompt: str) -> Diagnosis:
        raise QuotaExceededError("Gemini quota exceeded for gemini-test")

    provider = FakeProvider(answer=answer)
    monkeypatch.setattr(cli, "get_provider", lambda name, model: provider)
    assert cli.main(["--db", str(db_file), "diagnose", "--all"]) == 1
    out = capsys.readouterr().out
    assert f"Stopped after 0 of {len(SCENARIOS)} scenarios" in out
    assert len(provider.calls) == 1  # no further calls once the quota is gone
