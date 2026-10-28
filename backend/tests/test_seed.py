import random
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel

from postback_debugger.data import seed
from postback_debugger.data.db import connect
from postback_debugger.data.models import (
    AttributionStatus,
    Click,
    Event,
    FailureType,
    Install,
    Partner,
    PostbackLog,
    PostbackStatus,
    PostbackType,
)
from postback_debugger.data.scenarios import SCENARIOS, SCENARIOS_BY_TYPE
from postback_debugger.data.seed import (
    OK,
    PARTNERS,
    SCENARIO_BUILDERS,
    Dataset,
    build_dataset,
    main,
    render_url,
    seed_database,
)

MODELS: dict[str, type[BaseModel]] = {
    "partners": Partner,
    "clicks": Click,
    "installs": Install,
    "events": Event,
    "postback_logs": PostbackLog,
}


# --- helpers ---------------------------------------------------------------------------


def _click(db: sqlite3.Connection, failure_type: FailureType) -> Click:
    click_id = SCENARIOS_BY_TYPE[failure_type].click_id
    row = db.execute("SELECT * FROM clicks WHERE click_id = ?", (click_id,)).fetchone()
    assert row is not None, f"missing click {click_id}"
    return Click.model_validate(dict(row))


def _partner(db: sqlite3.Connection, partner_id: str) -> Partner:
    row = db.execute("SELECT * FROM partners WHERE partner_id = ?", (partner_id,)).fetchone()
    return Partner.model_validate(dict(row))


def _installs_on_device(db: sqlite3.Connection, device_id: str) -> list[Install]:
    rows = db.execute("SELECT * FROM installs WHERE device_id = ?", (device_id,)).fetchall()
    return [Install.model_validate(dict(r)) for r in rows]


def _events(db: sqlite3.Connection, install_id: str) -> list[Event]:
    rows = db.execute(
        "SELECT * FROM events WHERE install_id = ? ORDER BY event_time", (install_id,)
    ).fetchall()
    return [Event.model_validate(dict(r)) for r in rows]


def _postbacks(db: sqlite3.Connection, click_id: str) -> list[PostbackLog]:
    rows = db.execute(
        "SELECT * FROM postback_logs WHERE click_id = ? ORDER BY sent_at, attempt", (click_id,)
    ).fetchall()
    return [PostbackLog.model_validate(dict(r)) for r in rows]


def _single_install(db: sqlite3.Connection, click: Click) -> Install:
    installs = _installs_on_device(db, click.device_id)
    assert len(installs) == 1
    return installs[0]


# --- dataset-wide checks ---------------------------------------------------------------


def test_every_failure_type_has_one_scenario_and_builder() -> None:
    assert [s.failure_type for s in SCENARIOS] == list(FailureType)
    assert set(SCENARIO_BUILDERS) == set(FailureType)
    assert len({s.click_id for s in SCENARIOS}) == len(SCENARIOS)


@pytest.mark.parametrize("table", list(MODELS))
def test_database_round_trips_to_models(db: sqlite3.Connection, table: str) -> None:
    rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
    stored = [MODELS[table].model_validate(dict(r)) for r in rows]
    assert stored == list(build_dataset().tables()[table])


def test_same_seed_gives_same_dataset() -> None:
    assert build_dataset(42).tables() == build_dataset(42).tables()


def test_different_seed_changes_background_traffic_only() -> None:
    a, b = build_dataset(1), build_dataset(2)
    assert a.clicks != b.clicks
    scenario_ids = {s.click_id for s in SCENARIOS}
    assert scenario_ids <= {c.click_id for c in a.clicks}
    assert scenario_ids <= {c.click_id for c in b.clicks}


def test_click_ids_do_not_reveal_scenarios(db: sqlite3.Connection) -> None:
    click_ids = [r["click_id"] for r in db.execute("SELECT click_id FROM clicks")]
    assert all(re.fullmatch(r"clk_[0-9a-f]{8}", c) for c in click_ids)


def test_foreign_keys_hold(db: sqlite3.Connection) -> None:
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_failed_postbacks_only_come_from_failure_scenarios(db: sqlite3.Connection) -> None:
    failing = {
        r["click_id"]
        for r in db.execute("SELECT DISTINCT click_id FROM postback_logs WHERE status = 'failed'")
    }
    expected = {
        SCENARIOS_BY_TYPE[t].click_id
        for t in (
            FailureType.PARTNER_4XX,
            FailureType.PARTNER_5XX,
            FailureType.TIMEOUT,
            FailureType.MISSING_MACRO,
            FailureType.DUPLICATE,
        )
    }
    assert failing == expected


def test_background_traffic_is_present(db: sqlite3.Connection) -> None:
    (clicks,) = db.execute("SELECT COUNT(*) FROM clicks").fetchone()
    assert clicks > len(SCENARIOS) + 40


# --- one test per scenario: the clues the agent will need ------------------------------


def test_delivered(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.NONE)
    install = _single_install(db, click)
    assert install.click_id == click.click_id
    postbacks = _postbacks(db, click.click_id)
    assert [p.postback_type for p in postbacks] == [PostbackType.INSTALL, PostbackType.EVENT]
    assert all(p.status is PostbackStatus.SUCCESS for p in postbacks)


def test_no_install(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.NO_INSTALL)
    assert _installs_on_device(db, click.device_id) == []
    assert _postbacks(db, click.click_id) == []


def test_attributed_to_other_click(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.ATTRIBUTED_TO_OTHER_CLICK)
    install = _single_install(db, click)
    assert install.attribution_status is AttributionStatus.ATTRIBUTED
    assert install.click_id is not None and install.click_id != click.click_id

    row = db.execute("SELECT * FROM clicks WHERE click_id = ?", (install.click_id,)).fetchone()
    winner = Click.model_validate(dict(row))
    assert winner.device_id == click.device_id
    assert winner.partner_id != click.partner_id
    assert click.clicked_at < winner.clicked_at < install.installed_at
    assert _postbacks(db, click.click_id) == []


def test_outside_attribution_window(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.OUTSIDE_ATTRIBUTION_WINDOW)
    install = _single_install(db, click)
    window = timedelta(hours=_partner(db, click.partner_id).attribution_window_hours)
    assert install.attribution_status is AttributionStatus.ORGANIC
    assert install.installed_at - click.clicked_at > window
    assert _postbacks(db, click.click_id) == []


def test_fraud_rejected(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.FRAUD_REJECTED)
    install = _single_install(db, click)
    assert install.attribution_status is AttributionStatus.REJECTED
    assert install.click_id == click.click_id
    assert install.rejection_reason
    assert install.installed_at - click.clicked_at < timedelta(seconds=10)
    assert _postbacks(db, click.click_id) == []


def test_event_not_mapped(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.EVENT_NOT_MAPPED)
    install = _single_install(db, click)
    mapping = _partner(db, click.partner_id).event_mapping
    unmapped = [e for e in _events(db, install.install_id) if e.event_name not in mapping]
    assert [e.event_name for e in unmapped] == ["purchase_v2"]

    postbacks = _postbacks(db, click.click_id)
    assert unmapped[0].event_id not in {p.event_id for p in postbacks}
    assert all(p.status is PostbackStatus.SUCCESS for p in postbacks)


def test_partner_4xx(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.PARTNER_4XX)
    partner = _partner(db, click.partner_id)
    (postback,) = _postbacks(db, click.click_id)
    assert postback.status is PostbackStatus.FAILED
    assert postback.http_status == 401
    assert partner.api_key_expires_at is not None
    assert postback.sent_at > partner.api_key_expires_at


def test_partner_5xx(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.PARTNER_5XX)
    postbacks = _postbacks(db, click.click_id)
    assert [p.attempt for p in postbacks] == [1, 2, 3]
    assert all(p.http_status == 503 for p in postbacks)
    assert all(p.status is PostbackStatus.FAILED for p in postbacks)


def test_timeout(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.TIMEOUT)
    timeout_ms = _partner(db, click.partner_id).timeout_ms
    postbacks = _postbacks(db, click.click_id)
    assert [p.attempt for p in postbacks] == [1, 2, 3]
    assert all(p.http_status is None and p.latency_ms >= timeout_ms for p in postbacks)
    assert all(p.error and "timeout" in p.error for p in postbacks)


def test_missing_macro(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.MISSING_MACRO)
    install = _single_install(db, click)
    assert install.advertising_id is None
    (postback,) = _postbacks(db, click.click_id)
    assert "{advertising_id}" in postback.url
    assert postback.http_status == 400


def test_duplicate(db: sqlite3.Connection) -> None:
    click = _click(db, FailureType.DUPLICATE)
    install = _single_install(db, click)
    purchases = [e for e in _events(db, install.install_id) if e.event_name == "purchase"]
    assert len(purchases) == 2
    assert purchases[0].revenue == purchases[1].revenue
    assert purchases[1].event_time - purchases[0].event_time < timedelta(minutes=1)

    event_postbacks = [p for p in _postbacks(db, click.click_id) if p.event_id]
    assert [p.http_status for p in event_postbacks] == [200, 409]


# --- helpers and CLI -------------------------------------------------------------------


def test_render_url_fills_and_encodes_macros() -> None:
    url = render_url("https://x.example/?a={a}&b={b}", {"a": "1 2&3", "b": "ok"})
    assert url == "https://x.example/?a=1%202%263&b=ok"


def test_render_url_leaves_unknown_or_empty_macros() -> None:
    url = render_url("https://x.example/?a={a}&b={b}", {"a": None})
    assert url == "https://x.example/?a={a}&b={b}"


def test_cli_writes_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "nested" / "mmp.db"
    main(["--db", str(db_path)])

    assert "Wrote" in capsys.readouterr().out
    conn = connect(db_path)
    try:
        (partners,) = conn.execute("SELECT COUNT(*) FROM partners").fetchone()
    finally:
        conn.close()
    assert partners == 4


def test_cli_reseeding_replaces_data(tmp_path: Path) -> None:
    db_path = tmp_path / "mmp.db"
    main(["--db", str(db_path)])
    main(["--db", str(db_path)])  # must not fail on duplicate primary keys

    conn = connect(db_path)
    try:
        (clicks,) = conn.execute("SELECT COUNT(*) FROM clicks").fetchone()
    finally:
        conn.close()
    assert clicks == len(build_dataset().clicks)


def test_failed_reseed_keeps_existing_data(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(conn: sqlite3.Connection, ds: Dataset) -> None:
        raise RuntimeError("insert failed")

    monkeypatch.setattr(seed, "write_dataset", fail)
    with pytest.raises(RuntimeError):
        seed_database(db)
    (clicks,) = db.execute("SELECT COUNT(*) FROM clicks").fetchone()
    assert clicks == len(build_dataset().clicks)


# --- send_postback guards --------------------------------------------------------------

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def _dataset_with_click() -> tuple[Dataset, Click]:
    ds = Dataset(PARTNERS, random.Random(0))
    return ds, ds.add_click("alpha_ads", T0)


def test_send_postback_rejects_rejected_install() -> None:
    ds, click = _dataset_with_click()
    install = ds.add_install(
        click.device_id,
        T0,
        status=AttributionStatus.REJECTED,
        click=click,
        rejection_reason="fraud",
    )
    with pytest.raises(ValueError, match="attributed"):
        ds.send_postback(click, install, T0, [OK])


def test_send_postback_rejects_event_from_other_install() -> None:
    ds, click = _dataset_with_click()
    install = ds.add_install(click.device_id, T0, status=AttributionStatus.ATTRIBUTED, click=click)
    other = ds.add_install("dev_other", T0, status=AttributionStatus.ORGANIC)
    event = ds.add_event(other, "purchase", T0, revenue=1.0)
    with pytest.raises(ValueError, match="does not belong"):
        ds.send_postback(click, install, T0, [OK], event=event)


def test_send_postback_rejects_unmapped_event() -> None:
    ds, click = _dataset_with_click()
    install = ds.add_install(click.device_id, T0, status=AttributionStatus.ATTRIBUTED, click=click)
    event = ds.add_event(install, "purchase_v2", T0)
    with pytest.raises(ValueError, match="no mapping"):
        ds.send_postback(click, install, T0, [OK], event=event)
