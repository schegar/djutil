/** Camelot key utilities: colours for badges and the wheel. */

const INNER_COLORS = [
  "#7c5ce0", "#8d5ad6", "#b055c9", "#d454a8", "#e0547e", "#e86a5e",
  "#e58a4a", "#dfa93b", "#c8c93f", "#9fd04a", "#63c96b", "#4bbf9b",
];
const OUTER_COLORS = [
  "#3d9bd6", "#37a3c2", "#37b0a8", "#3fbc7e", "#5cb95e", "#8db84c",
  "#b5b44b", "#d1a94a", "#e08d4e", "#e06e5c", "#dd5980", "#c957a6",
];

function parse(camelot: string): { num: number; letter: "A" | "B" } | null {
  const m = /^(\d{1,2})([AaBb])$/.exec(camelot.trim());
  if (!m) return null;
  const num = parseInt(m[1], 10);
  if (num < 1 || num > 12) return null;
  return { num, letter: m[2].toUpperCase() as "A" | "B" };
}

/** Parsed Camelot key, or null for invalid input. */
export function camelotParse(
  camelot: string | null | undefined,
): { num: number; letter: "A" | "B" } | null {
  return camelot ? parse(camelot) : null;
}

/** Canonical display form: "9A", "12B" (number first). */
export function camelotFormat(camelot: string | null | undefined): string {
  const p = camelotParse(camelot);
  return p ? `${p.num}${p.letter}` : "";
}

export function camelotColor(camelot: string | null | undefined): string {
  if (!camelot) return "#555";
  const p = parse(camelot);
  if (!p) return "#555";
  return (p.letter === "A" ? INNER_COLORS : OUTER_COLORS)[p.num - 1];
}

export const CAMELOT_KEYS: string[] = [
  ...Array.from({ length: 12 }, (_, i) => `${i + 1}A`),
  ...Array.from({ length: 12 }, (_, i) => `${i + 1}B`),
];
