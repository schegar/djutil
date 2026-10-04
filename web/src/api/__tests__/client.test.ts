import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, UnauthorizedError } from "../client";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("redirects to /login?next= on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "nope" }), { status: 401 }),
      ),
    );
    const assign = vi.fn();
    Object.defineProperty(window, "location", {
      value: {
        pathname: "/history",
        search: "?x=1",
        assign,
      },
      writable: true,
    });
    await expect(api.me()).rejects.toThrow(UnauthorizedError);
    expect(assign).toHaveBeenCalledWith("/login?next=%2Fhistory%3Fx%3D1");
  });

  it("does not redirect when already on /login", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    Object.defineProperty(window, "location", {
      value: { pathname: "/login", search: "", assign: vi.fn() },
      writable: true,
    });
    await expect(api.me()).rejects.toThrow();
  });

  it("throws on non-ok non-401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "oops" }), { status: 500 }),
      ),
    );
    await expect(api.facets()).rejects.toThrow("API 500");
  });
});
