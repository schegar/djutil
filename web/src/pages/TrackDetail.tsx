import { useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import type { components } from "../api/schema";
import { api } from "../api/client";
import { Badge } from "../components/ui/badge";
import { camelotColor } from "../lib/camelot";
import {
  cueKindLabel,
  formatDate,
  formatDateTime,
  formatDuration,
  formatMs,
} from "../lib/format";

function Field({ label, value }: { label: string; value: unknown }) {
  const v = value == null || value === "" ? "—" : String(value);
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-neutral-500">{label}</dt>
      <dd className="truncate text-sm">{v}</dd>
    </div>
  );
}

type TransitionStat = components["schemas"]["TransitionStatOut"];
type Suggestion = components["schemas"]["Suggestion"];

function TransitionStatList({ items }: { items: TransitionStat[] }) {
  if (items.length === 0)
    return <p className="text-sm text-neutral-500">None yet.</p>;
  return (
    <ul className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
      {items.map((tr) => (
        <li key={tr.other_track?.id}>
          <Link
            to={`/tracks/${encodeURIComponent(tr.other_track?.id ?? "")}`}
            className="flex items-center gap-3 px-3 py-2 hover:bg-neutral-900"
          >
            <span className="min-w-0 flex-1 truncate text-sm">
              {tr.other_track?.artist} – {tr.other_track?.title || "Untitled"}
            </span>
            {tr.other_track?.camelot && (
              <Badge
                className="text-black"
                style={{
                  backgroundColor: camelotColor(tr.other_track.camelot),
                }}
              >
                {tr.other_track.camelot}
              </Badge>
            )}
            <span className="text-xs text-neutral-500">
              {tr.count}×{tr.fav_count > 0 && ` · ★${tr.fav_count}`}
              {tr.avg_rating != null && ` · avg ${tr.avg_rating.toFixed(1)}`}
            </span>
          </Link>
          {tr.last_comment && (
            <p className="px-3 pb-2 text-xs text-neutral-500">
              “{tr.last_comment}”
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

function TransitionTabs({
  out,
  into,
}: {
  out: TransitionStat[];
  into: TransitionStat[];
}) {
  const [dir, setDir] = useState<"out" | "in">("out");
  return (
    <div>
      <div className="mb-2 flex gap-1">
        {(["out", "in"] as const).map((d) => (
          <button
            key={d}
            onClick={() => setDir(d)}
            className={`rounded-md px-2.5 py-1 text-xs ${
              dir === d
                ? "bg-neutral-700 text-neutral-100"
                : "text-neutral-500 hover:text-neutral-300"
            }`}
          >
            {d === "out" ? "Plays into →" : "← Comes from"} (
            {(d === "out" ? out : into).length})
          </button>
        ))}
      </div>
      <TransitionStatList items={dir === "out" ? out : into} />
    </div>
  );
}

function CompatibleTracks({ trackId }: { trackId: string }) {
  const comp = useQuery({
    queryKey: ["compatible", trackId],
    queryFn: () => api.compatible(trackId),
  });
  const items: Suggestion[] = comp.data ?? [];
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
        Compatible tracks
      </h2>
      {comp.isLoading ? (
        <p className="text-sm text-neutral-500">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-neutral-500">No compatible tracks.</p>
      ) : (
        <ol className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
          {items.slice(0, 20).map((sug) => (
            <li key={sug.track.id}>
              <Link
                to={`/tracks/${encodeURIComponent(sug.track.id)}`}
                className="flex items-center gap-3 px-3 py-2 hover:bg-neutral-900"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm">
                    {sug.track.artist} – {sug.track.title || <em>Untitled</em>}
                  </p>
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {sug.reasons.map((r, i) => (
                      <span
                        key={i}
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
      )}
    </section>
  );
}

export function TrackDetail() {
  const { id } = useParams<{ id: string }>();
  const track = useQuery({
    queryKey: ["track", id],
    queryFn: () => api.track(id!),
    enabled: !!id,
  });
  const t = track.data;

  if (track.isLoading) return <p className="p-8 text-neutral-500">Loading…</p>;
  if (!t) return <p className="p-8 text-neutral-500">Track not found.</p>;

  return (
    <div className="space-y-6" data-testid="track-detail">
      <div className="flex gap-4">
        {t.artwork_hash ? (
          <img
            src={api.artworkUrl(t.artwork_hash)}
            alt="Artwork"
            className="h-32 w-32 rounded-lg object-cover"
          />
        ) : (
          <div className="flex h-32 w-32 items-center justify-center rounded-lg bg-neutral-800 text-neutral-600">
            No art
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-xl font-bold">
            {t.title}
            {t.mix && <span className="text-neutral-400"> ({t.mix})</span>}
          </h1>
          <p className="text-neutral-300">{t.artist}</p>
          <div className="mt-2 flex items-center gap-2">
            {t.camelot && (
              <Badge
                className="text-black"
                style={{ backgroundColor: camelotColor(t.camelot) }}
              >
                {t.camelot}
              </Badge>
            )}
            <span className="text-sm text-neutral-400">
              {t.bpm?.toFixed(1)} BPM · {formatDuration(t.length_s)}
            </span>
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-4 rounded-lg border border-neutral-800 p-4 sm:grid-cols-3 lg:grid-cols-4">
        <Field label="Original artist" value={t.original_artist} />
        <Field label="Remixer" value={t.remixer} />
        <Field label="Composer" value={t.composer} />
        <Field label="Album" value={t.album} />
        <Field label="Genre" value={t.genre} />
        <Field label="Label" value={t.label} />
        <Field label="Key" value={t.key_name} />
        <Field label="Rating" value={t.rating} />
        <Field
          label="Plays"
          value={`${t.play_count ?? 0} (+${t.app_play_count ?? 0} in app)`}
        />
        <Field label="Comment" value={t.comment} />
        <Field label="Bitrate" value={t.bitrate ? `${t.bitrate} kbps` : null} />
        <Field label="Sample rate" value={t.sample_rate ? `${t.sample_rate} Hz` : null} />
        <Field label="Release" value={t.release_date ?? t.release_year} />
        <Field label="Date added" value={formatDate(t.date_added)} />
        <Field label="File" value={t.file_name} />
        <Field label="Path" value={t.file_path} />
      </dl>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Cues
        </h2>
        {t.cues.length === 0 ? (
          <p className="text-sm text-neutral-500">No cues.</p>
        ) : (
          <table className="w-full text-sm" data-testid="cues-table">
            <thead>
              <tr className="border-b border-neutral-800 text-left text-xs text-neutral-500">
                <th className="py-1 pr-3">In</th>
                <th className="py-1 pr-3">Out</th>
                <th className="py-1 pr-3">Kind</th>
                <th className="py-1 pr-3">Colour</th>
                <th className="py-1">Comment</th>
              </tr>
            </thead>
            <tbody>
              {t.cues.map((c) => (
                <tr key={c.id} className="border-b border-neutral-900">
                  <td className="py-1 pr-3 font-mono">{formatMs(c.in_ms)}</td>
                  <td className="py-1 pr-3 font-mono">{formatMs(c.out_ms)}</td>
                  <td className="py-1 pr-3">{cueKindLabel(c.kind)}</td>
                  <td className="py-1 pr-3">
                    {c.color != null && (
                      <span
                        className="inline-block h-3 w-3 rounded-full"
                        style={{
                          backgroundColor: `hsl(${(c.color * 47) % 360} 70% 55%)`,
                        }}
                      />
                    )}
                  </td>
                  <td className="py-1">{c.comment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="flex flex-wrap gap-4">
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            My Tags
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {t.my_tags.map((tag) => (
              <Link
                key={tag.id}
                to={`/?my_tag=${encodeURIComponent(tag.id)}`}
                className="rounded-full border border-neutral-700 px-2.5 py-0.5 text-xs hover:bg-neutral-800"
              >
                {tag.name}
              </Link>
            ))}
            {t.my_tags.length === 0 && (
              <span className="text-sm text-neutral-500">—</span>
            )}
          </div>
        </div>
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Playlists
          </h2>
          <div className="flex flex-wrap gap-1.5">
            {t.playlists.map((p) => (
              <Link
                key={p.id}
                to={`/?playlist=${encodeURIComponent(p.id)}`}
                className="rounded-full border border-neutral-700 px-2.5 py-0.5 text-xs hover:bg-neutral-800"
              >
                {p.name}
              </Link>
            ))}
            {t.playlists.length === 0 && (
              <span className="text-sm text-neutral-500">—</span>
            )}
          </div>
        </div>
      </section>

      {(t.transitions_out.length > 0 || t.transitions_in.length > 0) && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Transitions
          </h2>
          <TransitionTabs out={t.transitions_out} into={t.transitions_in} />
        </section>
      )}

      {t.sets.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
            Sets
          </h2>
          <ul className="flex flex-wrap gap-1.5">
            {t.sets.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/sets/${s.id}`}
                  className="rounded-full border border-neutral-700 px-2.5 py-0.5 text-xs hover:bg-neutral-800"
                >
                  {s.name ?? `Set ${s.id}`}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <CompatibleTracks trackId={t.id} />

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-neutral-400">
          Rekordbox play history
        </h2>
        {t.history.length === 0 ? (
          <p className="text-sm text-neutral-500">Never played.</p>
        ) : (
          <ul className="space-y-1 text-sm">
            {t.history.map((h) => (
              <li key={h.id} className="flex gap-3">
                <span className="w-40 shrink-0 text-neutral-500">
                  {formatDateTime(h.created_at)}
                </span>
                <Link
                  to={`/history/${encodeURIComponent(h.history_id)}`}
                  className="text-neutral-300 underline-offset-2 hover:underline"
                >
                  {h.history_name ?? h.history_id}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
