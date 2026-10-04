import createClient from "openapi-fetch";
import type { paths } from "./schema";

export class UnauthorizedError extends Error {}

const raw = createClient<paths>({
  baseUrl: typeof location !== "undefined" ? location.origin : undefined,
  credentials: "include",
  // Defer to the global fetch at call time so tests can stub it.
  fetch: (input: RequestInfo | URL, init?: RequestInit) =>
    globalThis.fetch(input, init),
});

/**
 * Wrapper around openapi-fetch that throws on !ok and redirects to
 * /login on 401 (keeping the current location in `next`).
 */
async function request<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await promise;
  if (response.status === 401 && !location.pathname.startsWith("/login")) {
    const next = location.pathname + location.search;
    location.assign(`/login?next=${encodeURIComponent(next)}`);
    throw new UnauthorizedError("unauthorized");
  }
  if (error !== undefined || !response.ok) {
    throw new Error(
      `API ${response.status}: ${JSON.stringify(error ?? response.statusText)}`,
    );
  }
  return data as T;
}

export const api = {
  login: (password: string) =>
    request(raw.POST("/api/auth/login", { body: { password } })),
  logout: () => request(raw.POST("/api/auth/logout")),
  me: () => request(raw.GET("/api/auth/me")),
  tracks: (query: Record<string, unknown>) =>
    request(
      raw.GET("/api/tracks", {
        params: { query: query as never },
      }),
    ),
  track: (id: string) =>
    request(raw.GET("/api/tracks/{track_id}", { params: { path: { track_id: id } } })),
  facets: () => request(raw.GET("/api/facets")),
  sessions: () => request(raw.GET("/api/history/sessions")),
  session: (id: string) =>
    request(
      raw.GET("/api/history/sessions/{session_id}", {
        params: { path: { session_id: id } },
      }),
    ),
  artworkUrl: (hash: string) => `/api/artwork/${hash}`,
  // live / sets / suggestions
  liveState: () => request(raw.GET("/api/live/state")),
  getAutoRecord: () => request(raw.GET("/api/live/auto-record")),
  putAutoRecord: (auto_record: boolean) =>
    request(raw.PUT("/api/live/auto-record", { body: { auto_record } })),
  sets: () => request(raw.GET("/api/sets")),
  setDetail: (id: number) =>
    request(
      raw.GET("/api/sets/{set_id}", { params: { path: { set_id: id } } }),
    ),
  startSet: (name?: string) =>
    request(raw.POST("/api/sets/start", { body: { name: name ?? null } })),
  stopSet: (id: number) =>
    request(
      raw.POST("/api/sets/{set_id}/stop", {
        params: { path: { set_id: id } },
      }),
    ),
  patchSet: (id: number, body: { name?: string | null; notes?: string | null }) =>
    request(
      raw.PATCH("/api/sets/{set_id}", {
        params: { path: { set_id: id } },
        body,
      }),
    ),
  deleteSet: (id: number) =>
    request(
      raw.DELETE("/api/sets/{set_id}", { params: { path: { set_id: id } } }),
    ),
  deleteEntry: (setId: number, entryId: number) =>
    request(
      raw.DELETE("/api/sets/{set_id}/entries/{entry_id}", {
        params: { path: { set_id: setId, entry_id: entryId } },
      }),
    ),
  patchTransition: (
    id: number,
    body: { favorite?: boolean; rating?: number | null; comment?: string | null },
  ) =>
    request(
      raw.PATCH("/api/transitions/{transition_id}", {
        params: { path: { transition_id: id } },
        body,
      }),
    ),
  importRb: (historyId: string) =>
    request(
      raw.POST("/api/sets/import-rb/{history_id}", {
        params: { path: { history_id: historyId } },
      }),
    ),
  importRbAll: () => request(raw.POST("/api/sets/import-rb")),
  compatible: (id: string) =>
    request(
      raw.GET("/api/tracks/{track_id}/compatible", {
        params: { path: { track_id: id } },
      }),
    ),
};
