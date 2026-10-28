from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from postback_debugger.data.models import (
    AttributionStatus,
    Click,
    Event,
    Install,
    Partner,
    PostbackLog,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _install(**overrides: object) -> Install:
    fields: dict[str, object] = {
        "install_id": "ins_1",
        "app_id": "com.example.app",
        "platform": "android",
        "device_id": "dev_1",
        "advertising_id": None,
        "installed_at": NOW,
        "attribution_status": "attributed",
        "click_id": "clk_1",
    }
    return Install.model_validate(fields | overrides)


def _postback(**overrides: object) -> PostbackLog:
    fields: dict[str, object] = {
        "postback_id": "pb_1",
        "partner_id": "alpha_ads",
        "click_id": "clk_1",
        "install_id": "ins_1",
        "event_id": None,
        "postback_type": "install",
        "url": "https://alpha-ads.example/postback",
        "attempt": 1,
        "status": "success",
        "http_status": 200,
        "response_body": "{}",
        "error": None,
        "latency_ms": 100,
        "sent_at": NOW,
    }
    return PostbackLog.model_validate(fields | overrides)


def test_partner_parses_event_mapping_from_json_string() -> None:
    partner = Partner.model_validate(
        {
            "partner_id": "p",
            "name": "P",
            "postback_url_template": "https://p.example/?c={click_id}",
            "event_mapping": '{"install": "inst"}',
            "attribution_window_hours": 24,
            "timeout_ms": 1000,
            "max_attempts": 1,
        }
    )
    assert partner.event_mapping == {"install": "inst"}


def test_click_parses_strings_into_typed_fields() -> None:
    click = Click.model_validate(
        {
            "click_id": "6ac769a09e4c2a71d35b3c09",
            "partner_id": "alpha_ads",
            "campaign_id": "cmp",
            "app_id": "com.example.app",
            "platform": "ios",
            "device_id": "dev_1",
            "clicked_at": "2026-10-01T10:00:00Z",
        }
    )
    assert click.platform == "ios"
    assert click.clicked_at == datetime(2026, 10, 1, 10, tzinfo=UTC)


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _install(installed_at=datetime(2026, 10, 1))


def test_records_are_immutable() -> None:
    install = _install()
    with pytest.raises(ValidationError):
        install.device_id = "other"  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _install(surprise="field")


@pytest.mark.parametrize(
    "overrides",
    [
        {"attribution_status": "attributed", "click_id": None},
        {"attribution_status": "organic", "click_id": "clk_1"},
        {"attribution_status": "rejected", "rejection_reason": None},
        {"attribution_status": "attributed", "rejection_reason": "fraud"},
    ],
)
def test_install_attribution_rules(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _install(**overrides)


def test_rejected_install_may_reference_the_claimed_click() -> None:
    install = _install(attribution_status="rejected", rejection_reason="fraud")
    assert install.attribution_status is AttributionStatus.REJECTED
    assert install.click_id == "clk_1"


def test_event_revenue_requires_currency() -> None:
    with pytest.raises(ValidationError):
        Event(event_id="e", install_id="i", event_name="purchase", revenue=1.0, event_time=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"postback_type": "event", "event_id": None},
        {"postback_type": "install", "event_id": "evt_1"},
        {"status": "success", "http_status": 500},
        {"status": "success", "http_status": None},
        {"status": "failed", "http_status": 200},
        {"attempt": 0},
    ],
)
def test_postback_log_consistency_rules(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _postback(**overrides)


def test_failed_postback_without_response_is_valid() -> None:
    log = _postback(status="failed", http_status=None, response_body=None, error="timeout")
    assert log.error == "timeout"


@pytest.mark.parametrize("click_id", ["clk_1", "6AC769A09E4C2A71D35B3C09", "6ac769a09e4c", ""])
def test_click_id_must_be_an_object_id(click_id: str) -> None:
    with pytest.raises(ValidationError):
        Click.model_validate(
            {
                "click_id": click_id,
                "partner_id": "p",
                "campaign_id": "c",
                "app_id": "a",
                "platform": "ios",
                "device_id": "d",
                "clicked_at": "2026-10-01T10:00:00Z",
            }
        )
