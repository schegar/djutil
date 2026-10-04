import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatDate } from "../lib/format";

export function History() {
  const sessions = useQuery({
    queryKey: ["history-sessions"],
    queryFn: () => api.sessions(),
  });

  if (sessions.isLoading)
    return <p className="p-8 text-neutral-500">Loading…</p>;

  return (
    <div className="space-y-2" data-testid="history-list">
      <h1 className="mb-3 text-lg font-bold">Play history</h1>
      {(sessions.data ?? []).map((s) => (
        <Link
          key={s.id}
          to={`/history/${encodeURIComponent(s.id)}`}
          className="flex items-center gap-3 rounded-lg border border-neutral-800 px-4 py-3 hover:bg-neutral-900"
        >
          <div className="min-w-0 flex-1">
            <div className="truncate">{s.name ?? s.id}</div>
            <div className="text-xs text-neutral-500">
              {formatDate(s.date_created)}
            </div>
          </div>
          <span className="text-sm text-neutral-400">
            {s.entry_count} tracks
          </span>
        </Link>
      ))}
    </div>
  );
}
