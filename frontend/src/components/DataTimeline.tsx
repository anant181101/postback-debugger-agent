import { useState, type ReactNode } from "react";
import type { ClickContext, Partner } from "../api";
import { formatOffset, formatTime } from "../format";
import { IconActivity, IconCopy } from "./Icons";
import { PartnerAvatar } from "./PartnerAvatar";

type Tone = "neutral" | "ok" | "warn" | "error";

interface Entry {
  key: string;
  time: string;
  title: string;
  tone: Tone;
  body?: ReactNode;
}

/** Turns the click's records into one list ordered by time. */
function buildEntries(context: ClickContext): Entry[] {
  const { click } = context;
  const entries: Entry[] = [
    {
      key: click.click_id,
      time: click.clicked_at,
      title: "Click registered",
      tone: "neutral",
      body: (
        <p>
          {click.partner_id} · campaign <span className="mono">{click.campaign_id}</span> · device{" "}
          <span className="mono">{click.device_id}</span>
        </p>
      ),
    },
  ];

  for (const other of context.other_clicks_on_device) {
    entries.push({
      key: other.click_id,
      time: other.clicked_at,
      title: "Another click on the same device",
      tone: "warn",
      body: (
        <p>
          <span className="mono">{other.click_id}</span> from {other.partner_id} ·{" "}
          {other.campaign_id}
        </p>
      ),
    });
  }

  for (const install of context.installs_on_device) {
    const ours = install.click_id === click.click_id;
    const status = install.attribution_status;
    entries.push({
      key: install.install_id,
      time: install.installed_at,
      title:
        status === "attributed"
          ? ours
            ? "Install attributed to this click"
            : "Install attributed to another click"
          : status === "rejected"
            ? "Install rejected"
            : "Organic install",
      tone: status === "attributed" && ours ? "ok" : status === "rejected" ? "error" : "warn",
      body: (
        <p>
          <span className="mono">{install.install_id}</span>
          {install.click_id && !ours && (
            <>
              {" "}
              · won by <span className="mono">{install.click_id}</span>
            </>
          )}
          {install.rejection_reason && (
            <>
              {" "}
              · <span className="mono">{install.rejection_reason}</span>
            </>
          )}{" "}
          · advertising id {install.advertising_id ? "present" : <strong>missing</strong>}
        </p>
      ),
    });
  }

  for (const event of context.events) {
    entries.push({
      key: event.event_id,
      time: event.event_time,
      title: `Event ${event.event_name}`,
      tone: "neutral",
      body:
        event.revenue !== null ? (
          <p>
            Revenue {event.revenue.toFixed(2)} {event.currency}
          </p>
        ) : undefined,
    });
  }

  for (const log of context.postback_logs) {
    const ok = log.status === "success";
    entries.push({
      key: log.postback_id,
      time: log.sent_at,
      title: `${log.postback_type === "install" ? "Install" : "Event"} postback · attempt ${log.attempt}`,
      tone: ok ? "ok" : "error",
      body: (
        <>
          <p className="mono url">{log.url}</p>
          <p className="status-line">
            <span className={`chip ${ok ? "chip-ok" : "chip-error"}`}>
              {log.http_status !== null ? `HTTP ${log.http_status}` : "No response"}
            </span>
            {log.error && <span className="mono">{log.error}</span>}
            {log.response_body && <span className="mono">{log.response_body}</span>}
            <span className="mono muted">
              {log.postback_id} · {log.latency_ms} ms
            </span>
          </p>
        </>
      ),
    });
  }

  return entries.sort((a, b) => Date.parse(a.time) - Date.parse(b.time));
}

function Timeline({ context }: { context: ClickContext }) {
  const start = context.click.clicked_at;
  return (
    <ol className="rail">
      {buildEntries(context).map((entry) => (
        <li key={entry.key} className={`rail-item tone-${entry.tone}`}>
          <span className="rail-dot" />
          <div className="rail-body">
            <div className="rail-head">
              <span className="rail-title mono">{entry.title}</span>
              <span className="rail-time mono" title={formatTime(entry.time)}>
                {formatOffset(start, entry.time)}
              </span>
            </div>
            {entry.body}
          </div>
        </li>
      ))}
      {context.installs_on_device.length === 0 && (
        <li className="rail-item tone-neutral">
          <span className="rail-dot" />
          <div className="rail-body">
            <span className="rail-title mono muted">No install ever recorded on this device</span>
          </div>
        </li>
      )}
    </ol>
  );
}

function PartnerConfig({ partner }: { partner: Partner }) {
  const rows: [string, ReactNode][] = [
    ["Attribution window", `${partner.attribution_window_hours} h`],
    ["Timeout", `${partner.timeout_ms} ms`],
    ["Max attempts", partner.max_attempts],
    ["API key expires", partner.api_key_expires_at ? formatTime(partner.api_key_expires_at) : "n/a"],
  ];
  return (
    <div className="config">
      <div className="config-head">
        <PartnerAvatar partnerId={partner.partner_id} size={24} />
        <strong>{partner.name}</strong>
        <span className="mono muted">{partner.partner_id}</span>
      </div>
      <dl className="kv">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd className="mono">{v}</dd>
          </div>
        ))}
      </dl>
      <span className="label muted">Event mapping</span>
      <table className="mapping">
        <tbody>
          {Object.entries(partner.event_mapping).map(([ours, theirs]) => (
            <tr key={ours}>
              <td className="mono">{ours}</td>
              <td className="muted">→</td>
              <td className="mono">{theirs}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <span className="label muted">Postback URL template</span>
      <p className="mono url">{partner.postback_url_template}</p>
    </div>
  );
}

function RawJson({ context }: { context: ClickContext }) {
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(context, null, 2);
  return (
    <div className="code">
      <div className="code-head">
        <span className="label muted">context.json</span>
        <button
          type="button"
          className="btn btn-ghost btn-xs"
          onClick={() => {
            void navigator.clipboard?.writeText(json).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          <IconCopy size={12} /> {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>{json}</pre>
    </div>
  );
}

const TABS = ["Timeline", "Config", "Raw JSON"] as const;
type Tab = (typeof TABS)[number];

export function DataTimeline({ context }: { context: ClickContext }) {
  const [tab, setTab] = useState<Tab>("Timeline");
  return (
    <section className="panel evidence-panel" aria-label="Evidence data">
      <div className="panel-head">
        <span className="panel-title">
          <IconActivity size={16} /> Evidence data
        </span>
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      {tab === "Timeline" && <Timeline context={context} />}
      {tab === "Config" &&
        context.partners.map((p) => <PartnerConfig key={p.partner_id} partner={p} />)}
      {tab === "Raw JSON" && <RawJson context={context} />}
    </section>
  );
}
