import type { ClickContext } from "./api";

export type StageStatus = "ok" | "warn" | "error" | "missing";

export interface Stage {
  key: "click" | "install" | "events" | "postbacks";
  label: string;
  status: StageStatus;
  headline: string;
  detail: string;
  badge?: string;
  at: string | null; // when the stage first happened, for "+1h 0m" offsets
}

/** Summarises the click's lifecycle into four stages, from the raw data alone (no model). */
export function buildJourney(context: ClickContext): Stage[] {
  const { click } = context;
  const partner = context.partners.find((p) => p.partner_id === click.partner_id);
  const install = context.installs_on_device[0];

  const clickStage: Stage = {
    key: "click",
    label: "Click",
    status: "ok",
    headline: `Click on ${click.partner_id}`,
    detail: click.campaign_id,
    at: click.clicked_at,
  };

  let installStage: Stage;
  if (!install) {
    installStage = {
      key: "install",
      label: "Install",
      status: "missing",
      headline: "No install",
      detail: "Nothing recorded on this device",
      at: null,
    };
  } else {
    const base = { key: "install" as const, label: "Install", at: install.installed_at };
    if (install.attribution_status === "rejected") {
      installStage = {
        ...base,
        status: "error",
        headline: "Rejected by fraud checks",
        detail: install.rejection_reason ?? "",
      };
    } else if (install.click_id === click.click_id) {
      installStage = {
        ...base,
        status: "ok",
        headline: "Attributed to this click",
        detail: install.install_id,
      };
    } else if (install.attribution_status === "organic") {
      installStage = {
        ...base,
        status: "warn",
        headline: "Organic install",
        detail: "No click won attribution",
      };
    } else {
      installStage = {
        ...base,
        status: "warn",
        headline: "Attributed elsewhere",
        detail: `Won by ${install.click_id}`,
      };
    }
  }

  const events = context.events;
  const unmapped = partner ? events.filter((e) => !(e.event_name in partner.event_mapping)) : [];
  const eventsStage: Stage =
    events.length === 0
      ? {
          key: "events",
          label: "Events",
          status: "missing",
          headline: "None recorded",
          detail: "No in-app events",
          at: null,
        }
      : {
          key: "events",
          label: "Events",
          status: unmapped.length ? "warn" : "ok",
          headline: `${events.length} tracked`,
          detail: unmapped.length
            ? `${unmapped.map((e) => e.event_name).join(", ")} not mapped`
            : [...new Set(events.map((e) => e.event_name))].join(", "),
          at: events[0].event_time,
        };

  const logs = context.postback_logs;
  const delivered = logs.filter((l) => l.status === "success").length;
  const failed = logs.length - delivered;
  const lastFailure = [...logs].reverse().find((l) => l.status === "failed");
  const postbackStage: Stage =
    logs.length === 0
      ? {
          key: "postbacks",
          label: "Postbacks",
          status: "missing",
          headline: "None sent",
          detail: "No postback was attempted",
          at: null,
        }
      : {
          key: "postbacks",
          label: "Postbacks",
          status: failed ? "error" : "ok",
          headline: lastFailure
            ? lastFailure.http_status !== null
              ? `HTTP ${lastFailure.http_status}`
              : (lastFailure.error ?? "No response")
            : "All delivered",
          detail: lastFailure ? (lastFailure.response_body ?? lastFailure.url) : `${delivered} sent`,
          badge: `${delivered} ok · ${failed} failed`,
          at: logs[0].sent_at,
        };

  return [clickStage, installStage, eventsStage, postbackStage];
}
