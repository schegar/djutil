/** Library filter state <-> URLSearchParams (de)serialization. */

export interface TrackFilters {
  q: string;
  bpmMin: number | null;
  bpmMax: number | null;
  camelot: string[];
  genre: string[];
  source: string[];
  myTag: string | null;
  playlist: string | null;
  ratingMin: number | null;
  addedFrom: string;
  addedTo: string;
  playCountMin: number | null;
  playCountMax: number | null;
  neverPlayed: boolean;
  sort: string;
  order: "asc" | "desc";
}

export const DEFAULT_FILTERS: TrackFilters = {
  q: "",
  bpmMin: null,
  bpmMax: null,
  camelot: [],
  genre: [],
  source: [],
  myTag: null,
  playlist: null,
  ratingMin: null,
  addedFrom: "",
  addedTo: "",
  playCountMin: null,
  playCountMax: null,
  neverPlayed: false,
  sort: "title",
  order: "asc",
};

const NUM_KEYS = {
  bpm_min: "bpmMin",
  bpm_max: "bpmMax",
  rating_min: "ratingMin",
  play_count_min: "playCountMin",
  play_count_max: "playCountMax",
} as const;

const STR_KEYS = {
  q: "q",
  my_tag: "myTag",
  playlist: "playlist",
  added_from: "addedFrom",
  added_to: "addedTo",
  sort: "sort",
  order: "order",
} as const;

const LIST_KEYS = {
  camelot: "camelot",
  genre: "genre",
  source: "source",
} as const;

export function filtersToParams(f: TrackFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.bpmMin != null) p.set("bpm_min", String(f.bpmMin));
  if (f.bpmMax != null) p.set("bpm_max", String(f.bpmMax));
  if (f.camelot.length) p.set("camelot", f.camelot.join(","));
  if (f.genre.length) p.set("genre", f.genre.join(","));
  if (f.source.length) p.set("source", f.source.join(","));
  if (f.myTag) p.set("my_tag", f.myTag);
  if (f.playlist) p.set("playlist", f.playlist);
  if (f.ratingMin != null) p.set("rating_min", String(f.ratingMin));
  if (f.addedFrom) p.set("added_from", f.addedFrom);
  if (f.addedTo) p.set("added_to", f.addedTo);
  if (f.playCountMin != null) p.set("play_count_min", String(f.playCountMin));
  if (f.playCountMax != null) p.set("play_count_max", String(f.playCountMax));
  if (f.neverPlayed) p.set("never_played", "true");
  if (f.sort !== "title") p.set("sort", f.sort);
  if (f.order !== "asc") p.set("order", f.order);
  return p;
}

export function paramsToFilters(p: URLSearchParams): TrackFilters {
  const f = { ...DEFAULT_FILTERS, camelot: [], genre: [], source: [] };
  for (const [k, prop] of Object.entries(STR_KEYS)) {
    const v = p.get(k);
    if (v) (f as Record<string, unknown>)[prop] = v;
  }
  for (const [k, prop] of Object.entries(NUM_KEYS)) {
    const v = p.get(k);
    if (v != null && v !== "") {
      const n = Number(v);
      if (!Number.isNaN(n)) (f as Record<string, unknown>)[prop] = n;
    }
  }
  for (const [k, prop] of Object.entries(LIST_KEYS)) {
    const v = p.get(k);
    if (v) (f as Record<string, unknown>)[prop] = v.split(",").filter(Boolean);
  }
  if (p.get("never_played") === "true") f.neverPlayed = true;
  if (f.order !== "desc") f.order = "asc";
  return f;
}

/** API query params derived from the filter state (minus UI-only keys). */
export function filtersToApiQuery(f: TrackFilters): Record<string, unknown> {
  const q: Record<string, unknown> = {};
  if (f.q) q.q = f.q;
  if (f.bpmMin != null) q.bpm_min = f.bpmMin;
  if (f.bpmMax != null) q.bpm_max = f.bpmMax;
  if (f.camelot.length) q.camelot = f.camelot.join(",");
  if (f.genre.length) q.genre = f.genre.join(",");
  if (f.source.length) q.source = f.source.join(",");
  if (f.myTag) q.my_tag = f.myTag;
  if (f.playlist) q.playlist = f.playlist;
  if (f.ratingMin != null) q.rating_min = f.ratingMin;
  if (f.addedFrom) q.added_from = f.addedFrom;
  if (f.addedTo) q.added_to = f.addedTo;
  if (f.playCountMin != null) q.play_count_min = f.playCountMin;
  if (f.playCountMax != null) q.play_count_max = f.playCountMax;
  if (f.neverPlayed) q.never_played = true;
  q.sort = f.sort;
  q.order = f.order;
  return q;
}
