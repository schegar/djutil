import { describe, expect, it } from "vitest";
import { rankColor } from "../rank";

describe("rankColor", () => {
  it("is green for a single entry", () => {
    expect(rankColor(0, 1)).toBe("hsl(145, 35%, 32%)");
  });

  it("interpolates best green -> worst orange-red", () => {
    expect(rankColor(0, 5)).toBe("hsl(145, 35%, 32%)");
    expect(rankColor(4, 5)).toBe("hsl(15, 35%, 32%)");
    expect(rankColor(2, 5)).toBe("hsl(80, 35%, 32%)");
  });

  it("clamps out-of-range indices", () => {
    expect(rankColor(-1, 3)).toBe("hsl(145, 35%, 32%)");
    expect(rankColor(9, 3)).toBe("hsl(15, 35%, 32%)");
  });
});
