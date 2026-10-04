/** Key/BPM compatibility hints shown between set entries. */

import { camelotFormat, camelotParse } from "./camelot";

/** e.g. "8A → 9A (+1)", "same key", "relative". */
export function keyHint(
  from: string | null | undefined,
  to: string | null | undefined,
): string {
  const a = camelotParse(from);
  const b = camelotParse(to);
  if (!a || !b) return "";
  if (a.num === b.num && a.letter === b.letter) return "same key";
  if (a.num === b.num) return "relative";
  if (a.letter === b.letter) {
    const diff = ((b.num - a.num + 12) % 12) || 12;
    const d = diff > 6 ? diff - 12 : diff;
    if (Math.abs(d) <= 2) {
      return `${camelotFormat(from)} → ${camelotFormat(to)} (${d > 0 ? "+" : ""}${d})`;
    }
  }
  return `${camelotFormat(from)} → ${camelotFormat(to)}`;
}

/** e.g. "128 → 126.5 (−1.2%)", "2× 64 → 128". */
export function bpmHint(
  from: number | null | undefined,
  to: number | null | undefined,
): string {
  if (!from || !to || from <= 0 || to <= 0) return "";
  const pct = ((to - from) / from) * 100;
  if (Math.abs(pct) <= 12) {
    return `${from.toFixed(1)} → ${to.toFixed(1)} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
  }
  if (to * 2 > from * 0.9 && to * 2 < from * 1.1) {
    return `½× ${to.toFixed(1)} → ${from.toFixed(1)}`;
  }
  if (from * 2 > to * 0.9 && from * 2 < to * 1.1) {
    return `2× ${from.toFixed(1)} → ${to.toFixed(1)}`;
  }
  return `${from.toFixed(1)} → ${to.toFixed(1)} (${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%)`;
}
