/** Live-state socket helpers: URL building, reconnect backoff, reducer. */

import type { components } from "../api/schema";

export type LiveState = components["schemas"]["LiveState"];

/** ws(s):// URL for a same-origin API path. */
export function wsUrl(path: string, loc = location): string {
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.host}${path}`;
}

/**
 * Reconnect backoff in ms: 1 s, 2 s, 4 s, … capped at 15 s.
 * `attempt` is the consecutive-failure count starting at 0.
 */
export function backoffDelay(attempt: number): number {
  return Math.min(1000 * 2 ** Math.max(0, attempt), 15000);
}

export interface LiveUi {
  state: LiveState | null;
  connected: boolean;
}

export type LiveAction =
  | { type: "state"; payload: LiveState }
  | { type: "connected"; value: boolean };

export function liveReducer(ui: LiveUi, action: LiveAction): LiveUi {
  switch (action.type) {
    case "state":
      return { ...ui, state: action.payload };
    case "connected":
      return ui.connected === action.value
        ? ui
        : { ...ui, connected: action.value };
  }
}
