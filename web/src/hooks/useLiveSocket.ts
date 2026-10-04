import { useEffect, useReducer, useRef } from "react";
import { api } from "../api/client";
import {
  backoffDelay,
  liveReducer,
  wsUrl,
  type LiveUi,
} from "../lib/live";

/**
 * Streams LiveState from /api/live/ws. On disconnect it retries with
 * exponential backoff and polls GET /api/live/state every 5 s meanwhile.
 */
export function useLiveSocket(): LiveUi {
  const [ui, dispatch] = useReducer(liveReducer, {
    state: null,
    connected: false,
  });
  const connectedRef = useRef(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempts = 0;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const setConnected = (v: boolean) => {
      connectedRef.current = v;
      dispatch({ type: "connected", value: v });
    };

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl("/api/live/ws"));
      ws.onopen = () => {
        attempts = 0;
        setConnected(true);
      };
      ws.onmessage = (e) => {
        try {
          dispatch({ type: "state", payload: JSON.parse(e.data) });
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = (e) => {
        ws = null;
        if (e.code === 4401) return; // unauthenticated; redirect handled by api
        setConnected(false);
        if (!closed) {
          retryTimer = setTimeout(connect, backoffDelay(attempts++));
        }
      };
      ws.onerror = () => ws?.close();
    };

    // Fallback polling while the socket is down.
    const poll = setInterval(() => {
      if (connectedRef.current) return;
      api
        .liveState()
        .then((s) => dispatch({ type: "state", payload: s }))
        .catch(() => {});
    }, 5000);

    connect();
    return () => {
      closed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      clearInterval(poll);
      ws?.close();
    };
  }, []);

  return ui;
}
