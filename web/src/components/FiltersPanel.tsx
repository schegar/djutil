import type { components } from "../api/schema";
import type { TrackFilters } from "../lib/filters";
import { CamelotWheel } from "./CamelotWheel";
import { RangeSlider } from "./ui/slider";
import { Input } from "./ui/input";

type Facets = components["schemas"]["Facets"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 border-b border-neutral-800 pb-4">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
        {title}
      </h3>
      {children}
    </div>
  );
}

function TreeSelect({
  nodes,
  value,
  onChange,
  depth = 0,
}: {
  nodes: { id: string; name?: string | null; children?: unknown[] }[];
  value: string | null;
  onChange: (v: string | null) => void;
  depth?: number;
}) {
  return (
    <>
      {nodes.map((n) => (
        <div key={n.id}>
          <button
            type="button"
            onClick={() => onChange(value === n.id ? null : n.id)}
            className={`block w-full truncate rounded px-2 py-1 text-left text-sm ${
              value === n.id
                ? "bg-neutral-700 text-neutral-100"
                : "text-neutral-300 hover:bg-neutral-800"
            }`}
            style={{ paddingLeft: `${8 + depth * 14}px` }}
          >
            {n.name ?? n.id}
          </button>
          {n.children && n.children.length > 0 && (
            <TreeSelect
              nodes={n.children as typeof nodes}
              value={value}
              onChange={onChange}
              depth={depth + 1}
            />
          )}
        </div>
      ))}
    </>
  );
}

export function FiltersPanel({
  filters,
  facets,
  onChange,
}: {
  filters: TrackFilters;
  facets: Facets | undefined;
  onChange: (f: Partial<TrackFilters>) => void;
}) {
  const bpmLo = facets?.bpm_min ?? 0;
  const bpmHi = facets?.bpm_max ?? 200;
  const camelotCounts = Object.fromEntries(
    (facets?.camelots ?? []).map((c) => [c.name ?? "", c.count]),
  );

  return (
    <div className="space-y-4" data-testid="filters-panel">
      <Section title="BPM">
        <RangeSlider
          value={[filters.bpmMin ?? bpmLo, filters.bpmMax ?? bpmHi]}
          min={Math.floor(bpmLo)}
          max={Math.ceil(bpmHi) || 200}
          onValueChange={([lo, hi]) =>
            onChange({
              bpmMin: lo <= bpmLo ? null : lo,
              bpmMax: hi >= bpmHi ? null : hi,
            })
          }
        />
        <div className="flex justify-between text-xs text-neutral-400">
          <span>{(filters.bpmMin ?? bpmLo).toFixed(0)}</span>
          <span>{(filters.bpmMax ?? bpmHi).toFixed(0)}</span>
        </div>
      </Section>

      <Section title="Key (Camelot)">
        <CamelotWheel
          selected={filters.camelot}
          counts={camelotCounts}
          onChange={(v) => onChange({ camelot: v })}
        />
      </Section>

      <Section title="Genre">
        <div className="max-h-48 space-y-0.5 overflow-y-auto">
          {(facets?.genres ?? []).map((g) => (
            <label
              key={g.name}
              className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-neutral-800"
            >
              <input
                type="checkbox"
                checked={filters.genre.includes(g.name ?? "")}
                onChange={() =>
                  onChange({
                    genre: filters.genre.includes(g.name ?? "")
                      ? filters.genre.filter((x) => x !== g.name)
                      : [...filters.genre, g.name ?? ""],
                  })
                }
                className="accent-neutral-300"
              />
              <span className="flex-1 truncate">{g.name}</span>
              <span className="text-xs text-neutral-500">{g.count}</span>
            </label>
          ))}
        </div>
      </Section>

      {(facets?.sources ?? []).length > 0 && (
        <Section title="Source">
          <div className="space-y-0.5">
            {(facets?.sources ?? []).map((src) => (
              <label
                key={src.name}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm hover:bg-neutral-800"
              >
                <input
                  type="checkbox"
                  checked={filters.source.includes(src.name ?? "")}
                  onChange={() =>
                    onChange({
                      source: filters.source.includes(src.name ?? "")
                        ? filters.source.filter((x) => x !== src.name)
                        : [...filters.source, src.name ?? ""],
                    })
                  }
                  className="accent-neutral-300"
                />
                <span className="flex-1 truncate">
                  {src.name === "other_stream" ? "other streaming" : src.name}
                </span>
                <span className="text-xs text-neutral-500">{src.count}</span>
              </label>
            ))}
          </div>
        </Section>
      )}

      <Section title="My Tags">
        <TreeSelect
          nodes={(facets?.my_tags ?? []) as never}
          value={filters.myTag}
          onChange={(v) => onChange({ myTag: v })}
        />
      </Section>

      <Section title="Playlists">
        <TreeSelect
          nodes={(facets?.playlists ?? []) as never}
          value={filters.playlist}
          onChange={(v) => onChange({ playlist: v })}
        />
      </Section>

      <Section title="Rating">
        <div className="flex gap-1">
          {[0, 1, 2, 3, 4, 5].map((r) => (
            <button
              key={r}
              type="button"
              onClick={() =>
                onChange({ ratingMin: filters.ratingMin === r ? null : r })
              }
              className={`flex-1 rounded border px-1 py-1 text-xs ${
                filters.ratingMin != null && r >= filters.ratingMin
                  ? "border-neutral-300 bg-neutral-700"
                  : "border-neutral-700 text-neutral-400"
              }`}
            >
              {r === 0 ? "any" : "★".repeat(r)}
            </button>
          ))}
        </div>
      </Section>

      <Section title="Date added">
        <div className="flex gap-2">
          <Input
            type="date"
            value={filters.addedFrom}
            onChange={(e) => onChange({ addedFrom: e.target.value })}
          />
          <Input
            type="date"
            value={filters.addedTo}
            onChange={(e) => onChange({ addedTo: e.target.value })}
          />
        </div>
      </Section>

      <Section title="Play count">
        <div className="flex items-center gap-2">
          <Input
            type="number"
            placeholder="min"
            value={filters.playCountMin ?? ""}
            onChange={(e) =>
              onChange({
                playCountMin: e.target.value === "" ? null : +e.target.value,
              })
            }
          />
          <span className="text-neutral-500">–</span>
          <Input
            type="number"
            placeholder="max"
            value={filters.playCountMax ?? ""}
            onChange={(e) =>
              onChange({
                playCountMax: e.target.value === "" ? null : +e.target.value,
              })
            }
          />
        </div>
        <label className="flex cursor-pointer items-center gap-2 pt-1 text-sm">
          <input
            type="checkbox"
            checked={filters.neverPlayed}
            onChange={(e) => onChange({ neverPlayed: e.target.checked })}
            className="accent-neutral-300"
          />
          Never played
        </label>
      </Section>
    </div>
  );
}
