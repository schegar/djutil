import { Link, useNavigate, useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge } from "../components/ui/badge";
import { camelotColor } from "../lib/camelot";
import { formatDate, formatDateTime } from "../lib/format";

export function HistoryDetail() {
  const { id } = useParams<{ id: string }>();
  const session = useQuery({
    queryKey: ["history-session", id],
    queryFn: () => api.session(id!),
    enabled: !!id,
  });
  const navigate = useNavigate();
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["sets"], queryFn: () => api.sets() });
  const importedSet = sets.data?.find((x) => x.rb_history_id === id);
  const imp = useMutation({
    mutationFn: () => api.importRb(id!),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["sets"] });
      if (r.set_id != null) navigate(`/sets/${r.set_id}`);
    },
  });
  const s = session.data;

  if (session.isLoading)
    return <p className="p-8 text-neutral-500">Loading…</p>;
  if (!s) return <p className="p-8 text-neutral-500">Session not found.</p>;

  return (
    <div className="space-y-3" data-testid="history-detail">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold">{s.name ?? s.id}</h1>
          <p className="text-sm text-neutral-500">
            {formatDate(s.date_created)} · {s.entry_count} tracks
          </p>
        </div>
        {importedSet ? (
          <Link
            to={`/sets/${importedSet.id}`}
            className="rounded-md bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700"
          >
            Open set
          </Link>
        ) : (
          <button
            className="rounded-md bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700"
            onClick={() => imp.mutate()}
            disabled={imp.isPending}
          >
            {imp.isPending ? "Importing…" : "Import as set"}
          </button>
        )}
      </div>
      {imp.error && (
        <p className="text-sm text-red-400">
          {imp.error.message.includes("already_recorded_live")
            ? "This session was already recorded live."
            : imp.error.message}
        </p>
      )}
      <ol className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
        {s.entries.map((e) => (
          <li key={e.id} className="flex items-center gap-3 px-4 py-2">
            <span className="w-8 text-right text-xs text-neutral-500">
              {e.track_no}
            </span>
            <span className="w-32 shrink-0 text-xs text-neutral-500">
              {formatDateTime(e.created_at)}
            </span>
            {e.track ? (
              <Link
                to={`/tracks/${encodeURIComponent(e.content_id)}`}
                className="min-w-0 flex-1 hover:underline"
              >
                <span className="text-sm">
                  {e.track.artist} – {e.track.title}
                  {e.track.mix && (
                    <span className="text-neutral-500"> ({e.track.mix})</span>
                  )}
                </span>
              </Link>
            ) : (
              <span className="min-w-0 flex-1 text-sm text-neutral-500">
                {e.content_id}
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
          </li>
        ))}
      </ol>
    </div>
  );
}
