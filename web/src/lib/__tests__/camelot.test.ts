import { describe, expect, it } from "vitest";
import { CAMELOT_KEYS, camelotColor } from "../camelot";
import { cueKindLabel, formatDuration, formatMs } from "../format";

describe("camelotColor", () => {
  it("maps all 24 keys to distinct colours per wheel position", () => {
    const colors = new Set(CAMELOT_KEYS.map(camelotColor));
    expect(colors.size).toBe(24);
  });
  it("handles lowercase and whitespace", () => {
    expect(camelotColor("8a")).toBe(camelotColor("8A"));
    expect(camelotColor(" 11B ")).toBe(camelotColor("11B"));
  });
  it("returns grey for invalid/empty", () => {
    expect(camelotColor("bogus")).toBe("#555");
    expect(camelotColor(null)).toBe("#555");
    expect(camelotColor("13A")).toBe("#555");
  });
});

describe("formatting", () => {
  it("duration", () => {
    expect(formatDuration(245)).toBe("4:05");
    expect(formatDuration(null)).toBe("");
  });
  it("ms", () => {
    expect(formatMs(61234)).toBe("01:01.234");
    expect(formatMs(0)).toBe("00:00.000");
  });
  it("cue kind labels", () => {
    expect(cueKindLabel(0)).toBe("Memory");
    expect(cueKindLabel(1)).toBe("Hot A");
    expect(cueKindLabel(8)).toBe("Hot H");
    expect(cueKindLabel(9)).toBe("Kind 9");
  });
});
