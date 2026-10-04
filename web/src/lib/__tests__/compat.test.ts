import { describe, expect, it } from "vitest";
import { bpmHint, keyHint } from "../compat";

describe("keyHint", () => {
  it("same key", () => {
    expect(keyHint("8A", "8A")).toBe("same key");
  });
  it("relative major/minor", () => {
    expect(keyHint("8A", "8B")).toBe("relative");
  });
  it("energy +1/+2 in Camelot format (number first)", () => {
    expect(keyHint("8A", "9A")).toBe("8A → 9A (+1)");
    expect(keyHint("8A", "10A")).toBe("8A → 10A (+2)");
  });
  it("wraps 12 -> 1", () => {
    expect(keyHint("12B", "1B")).toBe("12B → 1B (+1)");
  });
  it("non-adjacent keys use Camelot format, not letter-first", () => {
    expect(keyHint("9A", "12B")).toBe("9A → 12B");
    expect(keyHint("4B", "7A")).toBe("4B → 7A");
  });
  it("invalid keys give empty", () => {
    expect(keyHint("X", "8A")).toBe("");
    expect(keyHint(null, "8A")).toBe("");
  });
});

describe("bpmHint", () => {
  it("small deltas show percent", () => {
    expect(bpmHint(128, 126.5)).toBe("128.0 → 126.5 (-1.2%)");
  });
  it("half/double time", () => {
    expect(bpmHint(128, 64)).toBe("½× 64.0 → 128.0");
    expect(bpmHint(64, 128)).toBe("2× 64.0 → 128.0");
  });
  it("missing bpm gives empty", () => {
    expect(bpmHint(null, 128)).toBe("");
    expect(bpmHint(0, 128)).toBe("");
  });
});
