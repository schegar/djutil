import { describe, expect, it } from "vitest";
import { backoffDelay, liveReducer, wsUrl, type LiveUi } from "../live";

describe("backoffDelay", () => {
  it("grows exponentially from 1s", () => {
    expect(backoffDelay(0)).toBe(1000);
    expect(backoffDelay(1)).toBe(2000);
    expect(backoffDelay(2)).toBe(4000);
    expect(backoffDelay(3)).toBe(8000);
  });

  it("caps at 15s", () => {
    expect(backoffDelay(10)).toBe(15000);
    expect(backoffDelay(100)).toBe(15000);
  });
});

describe("wsUrl", () => {
  it("maps http -> ws and https -> wss", () => {
    expect(
      wsUrl("/api/live/ws", {
        protocol: "http:",
        host: "x:8000",
      } as Location),
    ).toBe("ws://x:8000/api/live/ws");
    expect(
      wsUrl("/api/live/ws", {
        protocol: "https:",
        host: "dj.example.com",
      } as Location),
    ).toBe("wss://dj.example.com/api/live/ws");
  });
});

describe("liveReducer", () => {
  const ui: LiveUi = { state: null, connected: false };

  it("stores a new LiveState", () => {
    const payload = { agent: { connected: false } } as never;
    const next = liveReducer(ui, { type: "state", payload });
    expect(next.state).toBe(payload);
    expect(next.connected).toBe(false);
  });

  it("updates connected flag only on change", () => {
    const up = liveReducer(ui, { type: "connected", value: true });
    expect(up.connected).toBe(true);
    expect(liveReducer(up, { type: "connected", value: true })).toBe(up);
    expect(liveReducer(up, { type: "connected", value: false }).connected).toBe(
      false,
    );
  });
});
