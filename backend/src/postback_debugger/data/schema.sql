-- Synthetic MMP schema. Timestamps are ISO 8601 strings in UTC.
-- Running this script drops and recreates every table.

DROP TABLE IF EXISTS postback_logs;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS installs;
DROP TABLE IF EXISTS clicks;
DROP TABLE IF EXISTS partners;

CREATE TABLE partners (
    partner_id               TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    postback_url_template    TEXT NOT NULL,
    event_mapping            TEXT NOT NULL,  -- JSON object: MMP event name -> partner event name
    attribution_window_hours INTEGER NOT NULL CHECK (attribution_window_hours > 0),
    timeout_ms               INTEGER NOT NULL CHECK (timeout_ms > 0),
    max_attempts             INTEGER NOT NULL CHECK (max_attempts >= 1),
    api_key                  TEXT,
    api_key_expires_at       TEXT
);

CREATE TABLE clicks (
    click_id    TEXT PRIMARY KEY,
    partner_id  TEXT NOT NULL REFERENCES partners (partner_id),
    campaign_id TEXT NOT NULL,
    app_id      TEXT NOT NULL,
    platform    TEXT NOT NULL CHECK (platform IN ('android', 'ios')),
    device_id   TEXT NOT NULL,
    clicked_at  TEXT NOT NULL
);
CREATE INDEX idx_clicks_device ON clicks (device_id);

CREATE TABLE installs (
    install_id         TEXT PRIMARY KEY,
    app_id             TEXT NOT NULL,
    platform           TEXT NOT NULL CHECK (platform IN ('android', 'ios')),
    device_id          TEXT NOT NULL,
    advertising_id     TEXT,
    installed_at       TEXT NOT NULL,
    attribution_status TEXT NOT NULL
        CHECK (attribution_status IN ('attributed', 'organic', 'rejected')),
    click_id           TEXT REFERENCES clicks (click_id),
    rejection_reason   TEXT
);
CREATE INDEX idx_installs_device ON installs (device_id);
CREATE INDEX idx_installs_click ON installs (click_id);

CREATE TABLE events (
    event_id   TEXT PRIMARY KEY,
    install_id TEXT NOT NULL REFERENCES installs (install_id),
    event_name TEXT NOT NULL,
    revenue    REAL,
    currency   TEXT,
    event_time TEXT NOT NULL
);
CREATE INDEX idx_events_install ON events (install_id);

CREATE TABLE postback_logs (
    postback_id   TEXT PRIMARY KEY,
    partner_id    TEXT NOT NULL REFERENCES partners (partner_id),
    click_id      TEXT NOT NULL REFERENCES clicks (click_id),
    install_id    TEXT NOT NULL REFERENCES installs (install_id),
    event_id      TEXT REFERENCES events (event_id),
    postback_type TEXT NOT NULL CHECK (postback_type IN ('install', 'event')),
    url           TEXT NOT NULL,
    attempt       INTEGER NOT NULL CHECK (attempt >= 1),
    status        TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    http_status   INTEGER,
    response_body TEXT,
    error         TEXT,
    latency_ms    INTEGER NOT NULL CHECK (latency_ms >= 0),
    sent_at       TEXT NOT NULL
);
CREATE INDEX idx_postback_logs_click ON postback_logs (click_id);
CREATE INDEX idx_postback_logs_install ON postback_logs (install_id);
