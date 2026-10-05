import { useState } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Circle, Square } from "lucide-react";
import { api } from "../api/client";
import { Badge } from "../components/ui/badge";
import { useLiveSocket } from "../hooks/useLiveSocket";
import { camelotColor } from "../lib/camelot";
import { formatTime } from "../lib/format";
import { rankColor } from "../lib/rank";
import { cn } from "../lib/utils";

export function Live() {
  const { state, connected } = useLiveSocket();
  const qc = useQueryClient();
  const [setName, setSetName] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: ["sets"] });
  const start = useMutation({
    mutationFn: (name?: string) => api.startSet(name),
    onSuccess: () => {
      setSetName("");
      refresh();
    },
    onError: (e) => setActionError(e.message),
  });
  const stop = useMutation({
    mutationFn: (id: number) => api.stopSet(id),
    onSuccess: refresh,
    onError: (e) => setActionError(e.message),
  });
  const autoRec = useMutation({
    mutationFn: (v: boolean) => api.putAutoRecord(v),
    onError: (e) => setActionError(e.message),
  });

  const s = state;
  const activeSet = s?.active_set ?? null;

  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="live-page">
      {!connected && (
        <div className="rounded-md border border-amber-800 bg-amber-950/60 px-3 py-2 text-sm text-amber-300">
          Live connection lost — retrying; polling every 5 s meanwhile.
        </div>
      )}
      {actionError && (
        <div className="rounded-md border border-red-800 bg-red-950/60 px-3 py-2 text-sm text-red-300">
          {actionError}
        </div>
      )}

      {/* Agent status */}
      <div className="flex items-center gap-2 text-sm text-neutral-400">
        <span
          className={cn(
            "inline-block h-2.5 w-2.5 rounded-full",
            s?.agent.connected ? "bg-emerald-500" : "bg-neutral-600",
          )}
        />
        {s?.agent.connected
          ? `Agent connected${s.agent.hostname ? ` · ${s.agent.hostname}` : ""}${s.agent.rb_version ? ` · RB ${s.agent.rb_version}` : ""}`
          : "Agent offline"}
      </div>

      {/* Now playing */}
      <section className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Now playing
        </h2>
        {s?.now_playing ? (
          <Link
            to={`/tracks/${encodeURIComponent(s.now_playing.id)}`}
            className="flex items-center gap-4"
          >
            {s.now_playing.artwork_hash ? (
              <img
                src={api.artworkUrl(s.now_playing.artwork_hash)}
                alt=""
                className="h-24 w-24 rounded-lg object-cover"
              />
            ) : (
              <div className="flex h-24 w-24 items-center justify-center rounded-lg bg-neutral-800 text-neutral-600">
                No art
              </div>
            )}
            <div className="min-w-0">
              <p className="truncate text-lg font-bold">
                {s.now_playing.title || (
                  <em className="text-neutral-400">Untitled</em>
                )}
                {s.now_playing.mix && (
                  <span className="text-neutral-400"> ({s.now_playing.mix})</span>
                )}
              </p>
              <p className="truncate text-neutral-300">
                {s.now_playing.artist}
              </p>
              <div className="mt-1.5 flex items-center gap-2 text-sm text-neutral-400">
                {s.now_playing.camelot && (
                  <Badge
                    className="text-black"
                    style={{
                      backgroundColor: camelotColor(s.now_playing.camelot),
                    }}
                  >
                    {s.now_playing.camelot}
                  </Badge>
                )}
                {s.now_playing.bpm && (
                  <span>{s.now_playing.bpm.toFixed(1)} BPM</span>
                )}
                {s.now_playing_at && (
                  <span>played {formatTime(s.now_playing_at)}</span>
                )}
              </div>
            </div>
          </Link>
        ) : (
          <p className="text-sm text-neutral-500">Nothing playing.</p>
        )}
      </section>

      {/* Recording control */}
      <section className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            {activeSet ? (
              <>
                <Circle className="h-3 w-3 animate-pulse fill-red-500 text-red-500" />
                <span className="text-sm font-semibold text-red-400">REC</span>
                <input
                  className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
                  defaultValue={activeSet.name ?? ""}
                  key={activeSet.id}
                  onBlur={(e) => {
                    if (e.target.value && e.target.value !== activeSet.name) {
                      api.patchSet(activeSet.id, { name: e.target.value }).catch(() => {});
                    }
                  }}
                />
              </>
            ) : (
              <input
                className="min-w-0 flex-1 rounded border border-neutral-700 bg-neutral-900 px-2 py-1 text-sm"
                placeholder="Set name (optional)"
                value={setName}
                onChange={(e) => setSetName(e.target.value)}
              />
            )}
          </div>
          {activeSet ? (
            <button
              className="flex items-center gap-1.5 rounded-md bg-neutral-700 px-4 py-2 text-sm font-medium hover:bg-neutral-600"
              onClick={() => stop.mutate(activeSet.id)}
              disabled={stop.isPending}
            >
              <Square className="h-3.5 w-3.5" /> Stop
            </button>
          ) : (
            <button
              className="flex items-center gap-1.5 rounded-md bg-red-700 px-4 py-2 text-sm font-medium hover:bg-red-600"
              onClick={() => start.mutate(setName || undefined)}
              disabled={start.isPending}
            >
              <Circle className="h-3.5 w-3.5 fill-current" /> Start
            </button>
          )}
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm text-neutral-400">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={s?.auto_record ?? true}
            onChange={(e) => autoRec.mutate(e.target.checked)}
          />
          Auto-record sets
        </label>
      </section>

      {/* Session */}
      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Session
        </h2>
        {s && s.session.length > 0 ? (
          <ol className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
            {s.session.map((it, i) => (
              <li key={i} className="flex items-center gap-3 px-3 py-2">
                <span className="w-12 shrink-0 text-xs text-neutral-500">
                  {formatTime(it.played_at)}
                </span>
                {it.track ? (
                  <Link
                    to={`/tracks/${encodeURIComponent(it.track.id)}`}
                    className="min-w-0 flex-1 truncate text-sm hover:underline"
                  >
                    {it.track.artist} –{" "}
                    {it.track.title || <em>Untitled</em>}
                  </Link>
                ) : (
                  <span className="flex-1 text-sm text-neutral-500">?</span>
                )}
                {it.track?.camelot && (
                  <Badge
                    className="text-black"
                    style={{
                      backgroundColor: camelotColor(it.track.camelot),
                    }}
                  >
                    {it.track.camelot}
                  </Badge>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-neutral-500">No plays yet.</p>
        )}
      </section>

      {/* Suggestions */}
      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Suggestions
        </h2>
        {s && s.suggestions.length > 0 ? (
          <ol className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
            {s.suggestions.map((sug, i) => (
              <li key={sug.track.id}>
                <Link
                  to={`/tracks/${encodeURIComponent(sug.track.id)}`}
                  className="flex items-center gap-3 px-3 py-2 hover:bg-neutral-900"
                >
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-black"
                    style={{
                      backgroundColor: rankColor(i, s.suggestions.length),
                    }}
                  >
                    {i + 1}
                  </span>
                  {sug.track.artwork_hash ? (
                    <img
                      src={api.artworkUrl(sug.track.artwork_hash)}
                      alt=""
                      loading="lazy"
                      className="h-10 w-10 shrink-0 rounded object-cover"
                    />
                  ) : (
                    <div className="h-10 w-10 shrink-0 rounded bg-neutral-800" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm">
                      {sug.track.artist} –{" "}
                      {sug.track.title || <em>Untitled</em>}
                    </p>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {sug.reasons.map((r, j) => (
                        <span
                          key={j}
                          className="rounded-full bg-neutral-800 px-1.5 py-0.5 text-[10px] text-neutral-400"
                        >
                          {r.label}
                        </span>
                      ))}
                    </div>
                  </div>
                  {sug.track.camelot && (
                    <Badge
                      className="text-black"
                      style={{
                        backgroundColor: camelotColor(sug.track.camelot),
                      }}
                    >
                      {sug.track.camelot}
                    </Badge>
                  )}
                  <span className="w-12 text-right text-xs text-neutral-500">
                    {sug.score.toFixed(2)}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-neutral-500">No suggestions.</p>
        )}
      </section>
    </div>
  );
}
