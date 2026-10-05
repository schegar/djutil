/** Colour-coded rank badges for ranked lists (e.g. suggestions). */

/**
 * Colour for rank `index` (0-based, 0 = best) among `total` entries.
 * Interpolates hue from green (best) to orange-red (worst).
 */
export function rankColor(index: number, total: number): string {
  if (total <= 1) return "hsl(145, 65%, 50%)";
  const t = Math.min(1, Math.max(0, index / (total - 1)));
  return `hsl(${Math.round(145 - t * 130)}, 65%, 50%)`;
}
