import { useEffect, useMemo, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { Badge } from "../components/ui/badge";
import type { components } from "../api/schema";
import { camelotColor } from "../lib/camelot";
import { bpmHint, keyHint } from "../lib/compat";
import { debounce } from "../lib/debounce";
import { formatDateTime, formatDuration, formatOffset, formatTime } from "../lib/format";
import { cn } from "../lib/utils";

type SetDetailT = components["schemas"]["SetDetail"];
type TransitionT = components["schemas"]["TransitionOut"];
type EntryT = components["schemas"]["SetEntryOut"];

function TransitionRow({
  tr,
  setId,
}: {
  tr: TransitionT;
  setId: number;
}) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["set", setId] });
  const patch = useMutation({
    mutationFn: (body: Parameters<typeof api.patchTransition>[1]) =>
      api.patchTransition(tr.id, body),
    onSuccess: invalidate,
  });
  const commentDebounce = useRef(
    debounce((v: string) => patch.mutate({ comment: v || null }), 500),
  );
  useEffect(() => () => commentDebounce.current.flush(), []);

  const hint = [
    keyHint(tr.from_track?.camelot, tr.to_track?.camelot),
    bpmHint(tr.from_track?.bpm, tr.to_track?.bpm),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li
      className="flex flex-wrap items-center gap-2 border-y border-neutral-800/60 bg-neutral-900/40 px-3 py-1.5"
      data-testid={`transition-${tr.id}`}
    >
      <button
        aria-label="favourite"
        onClick={() => patch.mutate({ favorite: !tr.favorite })}
      >
        <Star
          className={cn(
            "h-4 w-4",
            tr.favorite ? "fill-amber-400 text-amber-400" : "text-neutral-600",
          )}
        />
      </button>
      <select
        className="rounded border border-neutral-700 bg-neutral-900 px-1 py-0.5 text-xs"
        value={tr.rating ?? ""}
        onChange={(e) =>
          patch.mutate({ rating: e.target.value ? Number(e.target.value) : null })
        }
      >
        <option value="">–</option>
        {[1, 2, 3, 4, 5].map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <input
        className="min-w-0 flex-1 rounded border border-neutral-800 bg-transparent px-1.5 py-0.5 text-xs text-neutral-300 placeholder:text-neutral-600"
        placeholder="transition note…"
        defaultValue={tr.comment ?? ""}
        onChange={(e) => commentDebounce.current.call(e.target.value)}
      />
      {hint && <span className="text-[11px] text-neutral-500">{hint}</span>}
    </li>
  );
}

export function SetDetail() {
  const { id } = useParams<{ id: string }>();
  const setId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const detail = useQuery<SetDetailT>({
    queryKey: ["set", setId],
    queryFn: () => api.setDetail(setId),
    enabled: Number.isFinite(setId),
  });
  const patchSet = useMutation({
    mutationFn: (body: Parameters<typeof api.patchSet>[1]) =>
      api.patchSet(setId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["set", setId] }),
  });
  const del = useMutation({
    mutationFn: () => api.deleteSet(setId),
    onSuccess: () => navigate("/sets"),
  });
  const delEntry = useMutation({
    mutationFn: (entryId: number) => api.deleteEntry(setId, entryId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["set", setId] }),
  });
  const notesDebounce = useRef(
    debounce((v: string) => patchSet.mutate({ notes: v || null }), 500),
  );
  useEffect(() => () => notesDebounce.current.flush(), []);

  const d = detail.data;
  const transitions = useMemo(() => {
    const m = new Map<number, TransitionT>();
    for (const t of d?.transitions ?? []) {
      if (t.to_entry_id != null) m.set(t.to_entry_id, t);
    }
    return m;
  }, [d]);

  if (detail.isLoading) return <p className="p-8 text-neutral-500">Loading…</p>;
  if (!d) return <p className="p-8 text-neutral-500">Set not found.</p>;

  return (
    <div className="space-y-4" data-testid="set-detail">
      <div className="flex flex-wrap items-center gap-3">
        <input
          className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-lg font-bold hover:border-neutral-700 focus:border-neutral-600 focus:outline-none"
          defaultValue={d.name ?? ""}
          key={d.id}
          placeholder="Set name"
          onBlur={(e) => {
            if (e.target.value !== (d.name ?? "")) {
              patchSet.mutate({ name: e.target.value || null });
            }
          }}
        />
        <Badge className="bg-neutral-800 text-neutral-300">
          {d.source === "rb_import" ? "rekordbox" : d.auto ? "auto" : "live"}
        </Badge>
        <button
          className="flex items-center gap-1 rounded-md border border-red-900 px-2.5 py-1.5 text-xs text-red-400 hover:bg-red-950"
          onClick={() => {
            if (window.confirm(`Delete "${d.name ?? `Set ${d.id}`}"?`)) {
              del.mutate();
            }
          }}
        >
          <Trash2 className="h-3.5 w-3.5" /> Delete
        </button>
      </div>
      <p className="text-sm text-neutral-500">
        {formatDateTime(d.started_at)}
        {d.duration_s != null && ` · ${formatDuration(d.duration_s)}`}
        {` · ${d.entry_count} tracks`}
        {d.fav_count > 0 && ` · ★${d.fav_count}`}
      </p>
      <textarea
        className="w-full rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm text-neutral-300 placeholder:text-neutral-600"
        rows={2}
        placeholder="Notes…"
        defaultValue={d.notes ?? ""}
        onChange={(e) => notesDebounce.current.call(e.target.value)}
      />

      <ol className="overflow-hidden rounded-lg border border-neutral-800">
        {d.entries.map((e: EntryT, i: number) => {
          const prev = i > 0 ? d.entries[i - 1] : null;
          const gap =
            prev && e.played_at && prev.played_at
              ? (new Date(e.played_at).getTime() -
                  new Date(prev.played_at).getTime()) /
                1000
              : null;
          const tr = transitions.get(e.id);
          return (
            <li key={e.id} className="contents">
              {tr && <TransitionRow tr={tr} setId={setId} />}
              <div className="flex items-center gap-3 px-3 py-2" data-testid={`entry-${e.id}`}>
                <span className="w-16 shrink-0 font-mono text-xs text-neutral-500">
                  {formatOffset(e.offset_seconds)}
                </span>
                <span className="w-12 shrink-0 text-xs text-neutral-500">
                  {formatTime(e.played_at)}
                </span>
                {e.track ? (
                  <Link
                    to={`/tracks/${encodeURIComponent(e.track.id)}`}
                    className="min-w-0 flex-1 truncate text-sm hover:underline"
                  >
                    {e.track.artist} – {e.track.title || <em>Untitled</em>}
                  </Link>
                ) : (
                  <span className="flex-1 text-sm text-neutral-500">
                    {e.track_id ?? "?"}
                  </span>
                )}
                {gap != null && gap > 120 && (
                  <span className="text-[10px] text-amber-500">
                    gap {formatDuration(gap)}
                  </span>
                )}
                {e.track?.bpm && (
                  <span className="text-xs text-neutral-500">
                    {e.track.bpm.toFixed(0)}
                  </span>
                )}
                {e.track?.camelot && (
                  <Badge
                    className="text-black"
                    style={{ backgroundColor: camelotColor(e.track.camelot) }}
                  >
                    {e.track.camelot}
                  </Badge>
                )}
                <button
                  aria-label="delete entry"
                  className="text-neutral-600 hover:text-red-400"
                  onClick={() => delEntry.mutate(e.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </li>
          );
        })}
      </ol>
      {d.entries.length === 0 && (
        <p className="text-sm text-neutral-500">No entries.</p>
      )}
    </div>
  );
}
