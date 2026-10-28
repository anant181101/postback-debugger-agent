import type { FailureType } from "./api";

export const FAILURE_LABELS: Record<FailureType, string> = {
  none: "Delivered",
  no_install: "No install",
  attributed_to_other_click: "Attributed to another click",
  outside_attribution_window: "Outside attribution window",
  fraud_rejected: "Rejected as fraud",
  event_not_mapped: "Event not mapped",
  partner_4xx: "Partner rejected (4xx)",
  partner_5xx: "Partner error (5xx)",
  timeout: "Partner timeout",
  missing_macro: "Missing macro",
  duplicate: "Duplicate",
};

export const FAILURE_CATEGORY: Record<FailureType, string> = {
  none: "Healthy",
  no_install: "Attribution",
  attributed_to_other_click: "Attribution",
  outside_attribution_window: "Attribution",
  fraud_rejected: "Fraud protection",
  event_not_mapped: "Configuration",
  partner_4xx: "Delivery",
  partner_5xx: "Delivery",
  timeout: "Delivery",
  missing_macro: "Configuration",
  duplicate: "Delivery",
};

// The badge colour: fine, an expected attribution outcome, fraud, or a delivery problem.
export type Tone = "ok" | "info" | "warn" | "error";

export const FAILURE_TONES: Record<FailureType, Tone> = {
  none: "ok",
  no_install: "info",
  attributed_to_other_click: "info",
  outside_attribution_window: "info",
  fraud_rejected: "warn",
  event_not_mapped: "error",
  partner_4xx: "error",
  partner_5xx: "error",
  timeout: "error",
  missing_macro: "error",
  duplicate: "error",
};

export const ALL_FAILURE_TYPES = Object.keys(FAILURE_LABELS) as FailureType[];

export function formatTime(iso: string): string {
  return (
    new Date(iso).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: "UTC",
    }) + " UTC"
  );
}

/** "+2h 5m", "+9d 0h", "+4s", relative to a reference time. */
export function formatOffset(fromIso: string, toIso: string): string {
  const seconds = Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 1000);
  const sign = seconds < 0 ? "-" : "+";
  let rest = Math.abs(seconds);
  const days = Math.floor(rest / 86400);
  rest %= 86400;
  const hours = Math.floor(rest / 3600);
  rest %= 3600;
  const minutes = Math.floor(rest / 60);
  const secs = rest % 60;
  if (days) return `${sign}${days}d ${hours}h`;
  if (hours) return `${sign}${hours}h ${minutes}m`;
  if (minutes) return `${sign}${minutes}m ${secs}s`;
  return `${sign}${secs}s`;
}

export function formatCost(cost: number | null): string {
  return cost === null ? "Free tier" : `$${cost.toFixed(4)}`;
}

/** Stable colour per partner, so the same partner always looks the same. */
export function partnerHue(partnerId: string): number {
  let hash = 0;
  for (const ch of partnerId) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
  return hash;
}

export function partnerInitials(partnerId: string): string {
  return partnerId
    .split(/[_-]/)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("")
    .slice(0, 2);
}
