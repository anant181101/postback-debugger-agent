"""Pydantic models for the synthetic MMP dataset.

Each record model mirrors one table in schema.sql.
"""

import json
from enum import StrEnum
from typing import Any, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Platform(StrEnum):
    ANDROID = "android"
    IOS = "ios"


class AttributionStatus(StrEnum):
    ATTRIBUTED = "attributed"
    ORGANIC = "organic"
    REJECTED = "rejected"


class PostbackType(StrEnum):
    INSTALL = "install"
    EVENT = "event"


class PostbackStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class FailureType(StrEnum):
    """Root causes the agent can diagnose for a click."""

    NONE = "none"
    NO_INSTALL = "no_install"
    ATTRIBUTED_TO_OTHER_CLICK = "attributed_to_other_click"
    OUTSIDE_ATTRIBUTION_WINDOW = "outside_attribution_window"
    FRAUD_REJECTED = "fraud_rejected"
    EVENT_NOT_MAPPED = "event_not_mapped"
    PARTNER_4XX = "partner_4xx"
    PARTNER_5XX = "partner_5xx"
    TIMEOUT = "timeout"
    MISSING_MACRO = "missing_macro"
    DUPLICATE = "duplicate"


def is_2xx(http_status: int | None) -> bool:
    """True when a partner response counts as a successful delivery."""
    return http_status is not None and 200 <= http_status < 300


class Record(BaseModel):
    """Base for all table records: immutable and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Partner(Record):
    partner_id: str
    name: str
    postback_url_template: str
    event_mapping: dict[str, str]  # MMP event name -> partner event name
    attribution_window_hours: int = Field(gt=0)
    timeout_ms: int = Field(gt=0)
    max_attempts: int = Field(ge=1)
    api_key: str | None = None
    api_key_expires_at: AwareDatetime | None = None

    @field_validator("event_mapping", mode="before")
    @classmethod
    def _parse_json(cls, value: Any) -> Any:
        # SQLite stores the mapping as a JSON string.
        if isinstance(value, str):
            return json.loads(value)
        return value


class Click(Record):
    click_id: str
    partner_id: str
    campaign_id: str
    app_id: str
    platform: Platform
    device_id: str
    clicked_at: AwareDatetime


class Install(Record):
    install_id: str
    app_id: str
    platform: Platform
    device_id: str
    advertising_id: str | None  # None when the user opted out of ad tracking
    installed_at: AwareDatetime
    attribution_status: AttributionStatus
    click_id: str | None  # attributed click, or the click a rejected install claimed
    rejection_reason: str | None = None

    @model_validator(mode="after")
    def _check_attribution(self) -> Self:
        if self.attribution_status is AttributionStatus.ATTRIBUTED and self.click_id is None:
            raise ValueError("attributed install requires click_id")
        if self.attribution_status is AttributionStatus.ORGANIC and self.click_id is not None:
            raise ValueError("organic install cannot have click_id")
        is_rejected = self.attribution_status is AttributionStatus.REJECTED
        if is_rejected != (self.rejection_reason is not None):
            raise ValueError("rejection_reason is required for rejected installs only")
        return self


class Event(Record):
    event_id: str
    install_id: str
    event_name: str
    revenue: float | None = None
    currency: str | None = None
    event_time: AwareDatetime

    @model_validator(mode="after")
    def _check_revenue(self) -> Self:
        if (self.revenue is None) != (self.currency is None):
            raise ValueError("revenue and currency must be set together")
        return self


class PostbackLog(Record):
    postback_id: str
    partner_id: str
    click_id: str
    install_id: str
    event_id: str | None  # None for install postbacks
    postback_type: PostbackType
    url: str
    attempt: int = Field(ge=1)
    status: PostbackStatus
    http_status: int | None  # None when no response was received
    response_body: str | None
    error: str | None
    latency_ms: int = Field(ge=0)
    sent_at: AwareDatetime

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if (self.postback_type is PostbackType.EVENT) != (self.event_id is not None):
            raise ValueError("event_id is required for event postbacks only")
        if is_2xx(self.http_status) != (self.status is PostbackStatus.SUCCESS):
            raise ValueError("status must be success exactly when http_status is 2xx")
        return self
