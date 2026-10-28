import { ALL_FAILURE_TYPES, FAILURE_CATEGORY, FAILURE_LABELS, FAILURE_TONES } from "../format";
import { IconClick, IconCpu, IconEvent, IconInstall, IconLayers, IconSend } from "./Icons";

const STAGES = [
  { icon: IconClick, label: "1. Click", text: "Ad click recorded with the user's device id." },
  { icon: IconInstall, label: "2. Install", text: "Matched to the last click inside the window." },
  { icon: IconEvent, label: "3. Events", text: "In-app events, sent only if the partner maps them." },
  { icon: IconSend, label: "4. Postbacks", text: "URL built from macros, retried on 5xx / timeout." },
];

const CATEGORIES = ["Healthy", "Attribution", "Fraud protection", "Configuration", "Delivery"];

export function EmptyState() {
  return (
    <>
      <section className="panel intro">
        <span className="label accent">Postback debugger</span>
        <h1>Why did this postback fail?</h1>
        <p className="muted">
          Select a scenario or enter a click ID. The debugger loads every related record from the
          database, then an LLM returns one root cause, the evidence behind it and the fix.
        </p>
      </section>

      <section className="panel lifecycle" aria-label="How a conversion flows">
        <div className="panel-head">
          <span className="label">Conversion lifecycle</span>
          <span className="label muted">What the debugger inspects</span>
        </div>
        <div className="stages">
          {STAGES.map(({ icon: Icon, label, text }) => (
            <div key={label} className="stage status-idle">
              <span className="stage-title">
                <span className="stage-mark">
                  <Icon size={13} />
                </span>
                {label}
              </span>
              <span className="stage-detail">{text}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel" aria-label="Detectable failures">
        <div className="panel-head">
          <span className="panel-title">
            <IconLayers size={16} /> Detectable root causes
          </span>
          <span className="label muted">{ALL_FAILURE_TYPES.length} types</span>
        </div>
        <div className="categories">
          {CATEGORIES.map((category) => (
            <div key={category} className="category">
              <span className="label muted">{category}</span>
              <div className="chips">
                {ALL_FAILURE_TYPES.filter((t) => FAILURE_CATEGORY[t] === category).map((t) => (
                  <span key={t} className={`chip chip-dot tone-${FAILURE_TONES[t]}`}>
                    {FAILURE_LABELS[t]}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <p className="note">
          <IconCpu size={14} />
          <span>
            Answers are checked against ground truth for the 11 seeded scenarios, so you can see
            how accurate each model is.
          </span>
        </p>
      </section>
    </>
  );
}
