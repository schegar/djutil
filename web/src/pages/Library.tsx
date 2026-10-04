import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  useInfiniteQuery,
  useQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { SlidersHorizontal, Star } from "lucide-react";
import { api } from "../api/client";
import type { components } from "../api/schema";
import {
  DEFAULT_FILTERS,
  filtersToApiQuery,
  filtersToParams,
  paramsToFilters,
  type TrackFilters,
} from "../lib/filters";
import { camelotColor } from "../lib/camelot";
import { formatDate, formatDuration } from "../lib/format";
import { FiltersPanel } from "../components/FiltersPanel";
import { Sheet } from "../components/ui/sheet";
import { Input } from "../components/ui/input";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

type Track = components["schemas"]["TrackOut"];

const PAGE_SIZE = 200;
const PRESETS_KEY = "djutil.filterPresets";

const COLUMNS: { key: string; label: string; sortable: boolean; className?: string }[] = [
  { key: "title", label: "Title", sortable: true, className: "flex-1" },
  { key: "artist", label: "Artist", sortable: true, className: "w-40" },
  { key: "bpm", label: "BPM", sortable: true, className: "w-16 text-right" },
  { key: "camelot", label: "Key", sortable: true, className: "w-16" },
  { key: "genre", label: "Genre", sortable: true, className: "w-28" },
  { key: "rating", label: "Rating", sortable: true, className: "w-20" },
  { key: "dj_play_count", label: "Plays", sortable: true, className: "w-14 text-right" },
  { key: "date_added", label: "Added", sortable: true, className: "w-24" },
  { key: "length_s", label: "Time", sortable: true, className: "w-14 text-right" },
];

function SourceBadge({ source }: { source: string }) {
  return (
    <Badge className="ml-1.5 bg-sky-900/60 align-middle text-[10px] text-sky-300">
      {source === "other_stream" ? "stream" : source}
    </Badge>
  );
}

function CamelotBadge({ value }: { value: string | null | undefined }) {
  if (!value) return null;
  return (
    <Badge
      className="w-9 justify-center text-black"
      style={{ backgroundColor: camelotColor(value) }}
    >
      {value}
    </Badge>
  );
}

function Stars({ n }: { n: number | null | undefined }) {
  return (
    <span className="inline-flex gap-px text-amber-400">
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          className={`h-3 w-3 ${i < (n ?? 0) ? "fill-amber-400" : "text-neutral-700"}`}
        />
      ))}
    </span>
  );
}

export function Library() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => paramsToFilters(params), [params]);
  const [searchText, setSearchText] = useState(filters.q);
  const [sheetOpen, setSheetOpen] = useState(false);
  const parentRef = useRef<HTMLDivElement>(null);

  // Debounced search -> q param.
  useEffect(() => {
    const t = setTimeout(() => {
      if (searchText !== filters.q) {
        const p = filtersToParams({ ...filters, q: searchText });
        setParams(p, { replace: true });
      }
    }, 250);
    return () => clearTimeout(t);
  }, [searchText, filters, setParams]);

  const facets = useQuery({ queryKey: ["facets"], queryFn: () => api.facets() });

  const query = useInfiniteQuery({
    queryKey: ["tracks", filtersToParams(filters).toString()],
    queryFn: ({ pageParam }) =>
      api.tracks({
        ...filtersToApiQuery(filters),
        limit: PAGE_SIZE,
        offset: pageParam,
      }) as Promise<{ items: Track[]; total: number }>,
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });

  const items = useMemo(
    () => query.data?.pages.flatMap((p) => p.items) ?? [],
    [query.data],
  );
  const total = query.data?.pages[0]?.total ?? 0;

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 20,
  });

  function update(patch: Partial<TrackFilters>) {
    setParams(filtersToParams({ ...filters, ...patch }), { replace: true });
  }

  function toggleSort(key: string) {
    if (filters.sort === key) {
      update({ order: filters.order === "asc" ? "desc" : "asc" });
    } else {
      update({ sort: key, order: "asc" });
    }
  }

  // Infinite load trigger.
  useEffect(() => {
    const rows = virtualizer.getVirtualItems();
    const last = rows[rows.length - 1];
    if (
      last &&
      last.index >= items.length - 30 &&
      query.hasNextPage &&
      !query.isFetchingNextPage
    ) {
      query.fetchNextPage();
    }
  }, [virtualizer.getVirtualItems(), items.length, query]);

  // Filter presets (localStorage: name -> query string).
  const [presets, setPresets] = useState<Record<string, string>>(() =>
    JSON.parse(localStorage.getItem(PRESETS_KEY) ?? "{}"),
  );
  function savePreset() {
    const name = prompt("Preset name");
    if (!name) return;
    const next = { ...presets, [name]: filtersToParams(filters).toString() };
    setPresets(next);
    localStorage.setItem(PRESETS_KEY, JSON.stringify(next));
  }
  function applyPreset(qs: string) {
    setParams(new URLSearchParams(qs), { replace: true });
  }

  const filtersPanel = (
    <FiltersPanel filters={filters} facets={facets.data} onChange={update} />
  );

  return (
    <div className="flex gap-4">
      {/* Desktop filter sidebar */}
      <aside className="hidden w-64 shrink-0 md:block">
        <div className="sticky top-16 max-h-[calc(100dvh-5rem)] overflow-y-auto rounded-lg border border-neutral-800 bg-neutral-900/50 p-4">
          {filtersPanel}
        </div>
      </aside>

      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2">
          <Input
            placeholder="Search title, artist, album…"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="max-w-md"
            data-testid="search-input"
          />
          <Button
            variant="secondary"
            size="sm"
            className="md:hidden"
            onClick={() => setSheetOpen(true)}
            data-testid="open-filters"
          >
            <SlidersHorizontal className="h-4 w-4" /> Filters
          </Button>
          <span className="ml-auto text-sm text-neutral-400" data-testid="total-count">
            {total.toLocaleString()} tracks
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          {Object.keys(presets).map((name) => (
            <button
              key={name}
              onClick={() => applyPreset(presets[name])}
              className="rounded-full border border-neutral-700 px-2 py-0.5 text-neutral-300 hover:bg-neutral-800"
            >
              {name}
            </button>
          ))}
          <button
            onClick={savePreset}
            className="rounded-full border border-dashed border-neutral-700 px-2 py-0.5 text-neutral-500 hover:text-neutral-300"
          >
            + Save preset
          </button>
          {filters !== DEFAULT_FILTERS && (
            <button
              onClick={() => setParams(new URLSearchParams(), { replace: true })}
              className="ml-2 text-neutral-500 underline hover:text-neutral-300"
            >
              Clear all
            </button>
          )}
        </div>

        {/* Desktop table */}
        <div
          ref={parentRef}
          className="hidden max-h-[calc(100dvh-12rem)] overflow-auto rounded-lg border border-neutral-800 md:block"
          data-testid="track-table"
        >
          <div className="sticky top-0 z-10 flex border-b border-neutral-800 bg-neutral-900 text-xs font-semibold text-neutral-400">
            <div className="w-12 px-2 py-2" />
            {COLUMNS.map((c) => (
              <button
                key={c.key}
                onClick={() => c.sortable && toggleSort(c.key)}
                className={`px-2 py-2 text-left ${c.className} ${
                  c.sortable ? "hover:text-neutral-100" : ""
                }`}
              >
                {c.label}
                {filters.sort === c.key && (
                  <span>{filters.order === "asc" ? " ▲" : " ▼"}</span>
                )}
              </button>
            ))}
          </div>
          <div
            style={{ height: virtualizer.getTotalSize(), position: "relative" }}
          >
            {virtualizer.getVirtualItems().map((v) => {
              const t = items[v.index];
              return (
                <Link
                  key={v.key}
                  to={`/tracks/${encodeURIComponent(t.id)}`}
                  className="absolute flex w-full items-center border-b border-neutral-900 px-0 text-sm hover:bg-neutral-900"
                  style={{ transform: `translateY(${v.start}px)`, height: v.size }}
                >
                  <div className="w-12 px-2">
                    {t.artwork_hash ? (
                      <img
                        src={api.artworkUrl(t.artwork_hash)}
                        alt=""
                        loading="lazy"
                        className="h-8 w-8 rounded object-cover"
                      />
                    ) : (
                      <div className="h-8 w-8 rounded bg-neutral-800" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1 px-2">
                    <div className="truncate">
                      {t.title || <em className="text-neutral-500">Untitled</em>}
                      {t.mix && (
                        <span className="text-neutral-500"> ({t.mix})</span>
                      )}
                      {t.source && t.source !== "local" && (
                        <SourceBadge source={t.source} />
                      )}
                    </div>
                  </div>
                  <div className="w-40 truncate px-2 text-neutral-400">{t.artist}</div>
                  <div className="w-16 px-2 text-right">{t.bpm?.toFixed(0)}</div>
                  <div className="w-16 px-2"><CamelotBadge value={t.camelot} /></div>
                  <div className="w-28 truncate px-2 text-neutral-400">{t.genre}</div>
                  <div className="w-20 px-2"><Stars n={t.rating} /></div>
                  <div className="w-14 px-2 text-right">{t.play_count}</div>
                  <div className="w-24 px-2 text-neutral-400">{formatDate(t.date_added)}</div>
                  <div className="w-14 px-2 text-right text-neutral-400">
                    {formatDuration(t.length_s)}
                  </div>
                </Link>
              );
            })}
          </div>
          {query.isLoading && (
            <div className="p-8 text-center text-neutral-500">Loading…</div>
          )}
          {query.isFetchingNextPage && (
            <div className="p-3 text-center text-xs text-neutral-500">
              Loading more…
            </div>
          )}
        </div>

        {/* Mobile list */}
        <MobileTrackList items={items} total={total} query={query} />
      </div>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen} title="Filters">
        {filtersPanel}
      </Sheet>
    </div>
  );
}

function MobileTrackList({
  items,
  total,
  query,
}: {
  items: Track[];
  total: number;
  query: UseInfiniteQueryResult<InfiniteData<{ items: Track[]; total: number }>>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => ref.current,
    estimateSize: () => 56,
    overscan: 15,
  });
  useEffect(() => {
    const rows = virtualizer.getVirtualItems();
    const last = rows[rows.length - 1];
    if (
      last &&
      last.index >= items.length - 30 &&
      query.hasNextPage &&
      !query.isFetchingNextPage
    ) {
      query.fetchNextPage();
    }
  }, [virtualizer.getVirtualItems(), items.length, query]);

  return (
    <div
      ref={ref}
      className="max-h-[calc(100dvh-13rem)] overflow-auto rounded-lg border border-neutral-800 md:hidden"
      data-testid="track-list-mobile"
    >
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((v) => {
          const t = items[v.index];
          return (
            <Link
              key={v.key}
              to={`/tracks/${encodeURIComponent(t.id)}`}
              className="absolute flex w-full items-center gap-3 border-b border-neutral-900 px-3 hover:bg-neutral-900"
              style={{ transform: `translateY(${v.start}px)`, height: v.size }}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">
                  {t.title || <em className="text-neutral-500">Untitled</em>}
                  {t.mix && <span className="text-neutral-500"> ({t.mix})</span>}
                  {t.source && t.source !== "local" && (
                    <SourceBadge source={t.source} />
                  )}
                </div>
                <div className="truncate text-xs text-neutral-400">{t.artist}</div>
              </div>
              <span className="w-10 text-right text-sm">{t.bpm?.toFixed(0)}</span>
              <CamelotBadge value={t.camelot} />
            </Link>
          );
        })}
      </div>
      {query.isLoading && total === 0 && (
        <div className="p-8 text-center text-neutral-500">Loading…</div>
      )}
    </div>
  );
}
