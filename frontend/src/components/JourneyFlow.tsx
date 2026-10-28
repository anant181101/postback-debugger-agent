import type { ClickContext } from "../api";
import { formatOffset } from "../format";
import { buildJourney, type Stage } from "../journey";
import { IconAlert, IconCheck, IconX } from "./Icons";

function StatusMark({ stage }: { stage: Stage }) {
  if (stage.status === "ok") return <IconCheck size={13} />;
  if (stage.status === "error") return <IconX size={13} />;
  if (stage.status === "warn") return <IconAlert size={13} />;
  return <span className="dash">—</span>;
}

/** The click's lifecycle: Click → Install → Events → Postbacks, built from data only. */
export function JourneyFlow({ context }: { context: ClickContext }) {
  const stages = buildJourney(context);
  const start = context.click.clicked_at;
  // Span covers every record, not just the first of each stage.
  const times = [
    ...context.other_clicks_on_device.map((c) => c.clicked_at),
    ...context.installs_on_device.map((i) => i.installed_at),
    ...context.events.map((e) => e.event_time),
    ...context.postback_logs.map((l) => l.sent_at),
  ];
  const last = times.reduce((a, b) => (Date.parse(b) > Date.parse(a) ? b : a), start);

  return (
    <section className="panel lifecycle" aria-label="Conversion lifecycle">
      <div className="panel-head">
        <span className="label">Conversion lifecycle</span>
        <span className="label muted">Total span {formatOffset(start, last)}</span>
      </div>
      <div className="stages">
        {stages.map((stage, i) => (
          <div key={stage.key} className={`stage status-${stage.status}`}>
            <div className="stage-top">
              <span className="stage-title">
                <span className="stage-mark">
                  <StatusMark stage={stage} />
                </span>
                {i + 1}. {stage.label}
              </span>
              {stage.badge && stage.status === "error" ? (
                <span className="chip chip-error">{stage.badge}</span>
              ) : (
                <span className="chip">{stage.at ? formatOffset(start, stage.at) : "n/a"}</span>
              )}
            </div>
            <span className="stage-headline">{stage.headline}</span>
            <span className="stage-detail mono">{stage.detail}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
