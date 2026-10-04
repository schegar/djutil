/** Formatting helpers. */

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const milli = Math.floor(ms % 1000);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${String(milli).padStart(3, "0")}`;
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return "";
  return d.slice(0, 10);
}

export function formatDateTime(d: string | null | undefined): string {
  if (!d) return "";
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return d;
  return dt.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(d: string | null | undefined): string {
  if (!d) return "";
  const dt = new Date(d);
  if (isNaN(dt.getTime())) return d;
  return dt.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** hh:mm:ss for set-entry offsets. */
export function formatOffset(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function cueKindLabel(kind: number | null | undefined): string {
  if (kind == null) return "";
  if (kind === 0) return "Memory";
  if (kind >= 1 && kind <= 8) return `Hot ${"ABCDEFGH"[kind - 1]}`;
  return `Kind ${kind}`;
}
