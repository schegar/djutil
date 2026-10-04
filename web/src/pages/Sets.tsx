import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { Badge } from "../components/ui/badge";
import { formatDateTime, formatDuration } from "../lib/format";

export function Sets() {
  const qc = useQueryClient();
  const sets = useQuery({ queryKey: ["sets"], queryFn: () => api.sets() });
  const importAll = useMutation({
    mutationFn: () => api.importRbAll(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sets"] }),
  });
  const res = importAll.data;

  return (
    <div className="space-y-4" data-testid="sets-page">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-lg font-bold">Sets</h1>
        <button
          className="rounded-md bg-neutral-800 px-3 py-1.5 text-sm hover:bg-neutral-700"
          onClick={() => importAll.mutate()}
          disabled={importAll.isPending}
        >
          {importAll.isPending
            ? "Importing…"
            : "Import Rekordbox history"}
        </button>
      </div>
      {res && (
        <p className="rounded-md border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm text-neutral-300">
          Imported {res.imported} · {res.skipped_already_imported} already
          imported · {res.skipped_already_live} already recorded live
        </p>
      )}
      {importAll.error && (
        <p className="text-sm text-red-400">{importAll.error.message}</p>
      )}

      {sets.isLoading ? (
        <p className="text-neutral-500">Loading…</p>
      ) : !sets.data?.length ? (
        <p className="text-sm text-neutral-500">
          No sets yet. Record live or import from Rekordbox history.
        </p>
      ) : (
        <ol className="divide-y divide-neutral-900 rounded-lg border border-neutral-800">
          {sets.data.map((s) => (
            <li key={s.id}>
              <Link
                to={`/sets/${s.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-neutral-900"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {s.name ?? `Set ${s.id}`}
                  </p>
                  <p className="text-xs text-neutral-500">
                    {formatDateTime(s.started_at)} · {s.entry_count} tracks
                    {s.duration_s != null && ` · ${formatDuration(s.duration_s)}`}
                    {s.fav_count > 0 && ` · ★${s.fav_count}`}
                  </p>
                </div>
                <Badge className="bg-neutral-800 text-neutral-300">
                  {s.source === "rb_import" ? "rekordbox" : (s.auto ? "auto" : "live")}
                </Badge>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
