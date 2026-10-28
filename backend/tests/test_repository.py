import sqlite3
from pathlib import Path

import pytest

from postback_debugger import repository
from postback_debugger.data.db import connect
from postback_debugger.data.models import FailureType
from postback_debugger.data.scenarios import SCENARIOS_BY_TYPE


def _click_id(failure_type: FailureType) -> str:
    return SCENARIOS_BY_TYPE[failure_type].click_id


def test_get_click(db: sqlite3.Connection) -> None:
    click = repository.get_click(db, _click_id(FailureType.TIMEOUT))
    assert click is not None and click.partner_id == "gamma_network"
    assert repository.get_click(db, "clk_00000000") is None


def test_get_partner(db: sqlite3.Connection) -> None:
    partner = repository.get_partner(db, "alpha_ads")
    assert partner is not None and partner.event_mapping["purchase"] == "purchase"
    assert repository.get_partner(db, "nope") is None


def test_device_queries_are_ordered_by_time(db: sqlite3.Connection) -> None:
    click = repository.get_click(db, _click_id(FailureType.ATTRIBUTED_TO_OTHER_CLICK))
    assert click is not None
    clicks = repository.get_clicks_for_device(db, click.device_id)
    assert [c.clicked_at for c in clicks] == sorted(c.clicked_at for c in clicks)
    assert len(clicks) == 2
    assert len(repository.get_installs_for_device(db, click.device_id)) == 1


def test_events_and_postbacks(db: sqlite3.Connection) -> None:
    click_id = _click_id(FailureType.DUPLICATE)
    logs = repository.get_postback_logs_for_click(db, click_id)
    assert [log.http_status for log in logs] == [200, 200, 409]

    events = repository.get_events_for_install(db, logs[0].install_id)
    assert [e.event_name for e in events] == ["purchase", "purchase"]

    assert repository.get_postback_log(db, logs[2].postback_id) == logs[2]
    assert repository.get_postback_log(db, "pb_missing") is None


def test_read_only_connection_rejects_writes(db_file: Path) -> None:
    conn = connect(db_file, read_only=True)
    try:
        assert repository.get_partner(conn, "alpha_ads") is not None
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM clicks")
    finally:
        conn.close()


def test_read_only_connection_does_not_create_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        connect(missing, read_only=True)
    assert not missing.exists()
