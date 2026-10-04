import { describe, expect, it } from "vitest";
import {
  DEFAULT_FILTERS,
  filtersToApiQuery,
  filtersToParams,
  paramsToFilters,
  type TrackFilters,
} from "../filters";

const full: TrackFilters = {
  q: "acid house",
  bpmMin: 120,
  bpmMax: 140,
  camelot: ["8A", "9B"],
  genre: ["Techno", "House"],
  source: ["spotify", "local"],
  myTag: "tag-1",
  playlist: "pl-9",
  ratingMin: 3,
  addedFrom: "2024-01-01",
  addedTo: "2024-12-31",
  playCountMin: 1,
  playCountMax: 10,
  neverPlayed: true,
  sort: "bpm",
  order: "desc",
};

describe("filters <-> URLSearchParams", () => {
  it("round-trips every filter type", () => {
    const back = paramsToFilters(filtersToParams(full));
    expect(back).toEqual(full);
  });

  it("drops empty/default values", () => {
    const p = filtersToParams(DEFAULT_FILTERS);
    expect(p.toString()).toBe("sort=title&order=asc".replace(/sort=title&?/, "").replace(/order=asc/, ""));
    // nothing survives from defaults except nothing at all:
    expect([...p.keys()]).toEqual([]);
  });

  it("drops empty strings and nulls", () => {
    const p = filtersToParams({
      ...DEFAULT_FILTERS,
      q: "",
      bpmMin: null,
      camelot: [],
      addedFrom: "",
      playCountMin: null,
      neverPlayed: false,
    });
    expect(p.toString()).toBe("");
  });

  it("ignores garbage numbers and caps order", () => {
    const f = paramsToFilters(new URLSearchParams("bpm_min=abc&order=sideways"));
    expect(f.bpmMin).toBeNull();
    expect(f.order).toBe("asc");
  });

  it("api query mirrors params", () => {
    const q = filtersToApiQuery(full) as Record<string, unknown>;
    expect(q.camelot).toBe("8A,9B");
    expect(q.genre).toBe("Techno,House");
    expect(q.source).toBe("spotify,local");
    expect(q.never_played).toBe(true);
    expect(q.sort).toBe("bpm");
    expect(q.order).toBe("desc");
  });
});
