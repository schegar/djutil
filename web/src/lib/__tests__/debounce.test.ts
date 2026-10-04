import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { debounce } from "../debounce";

describe("debounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces rapid calls into one trailing call", () => {
    const fn = vi.fn();
    const d = debounce(fn, 500);
    d.call("a");
    vi.advanceTimersByTime(300);
    d.call("b");
    vi.advanceTimersByTime(300);
    d.call("c");
    vi.advanceTimersByTime(500);
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith("c");
  });

  it("flush fires the pending call immediately", () => {
    const fn = vi.fn();
    const d = debounce(fn, 500);
    d.call("x");
    d.flush();
    expect(fn).toHaveBeenCalledWith("x");
    vi.advanceTimersByTime(1000);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("cancel drops the pending call", () => {
    const fn = vi.fn();
    const d = debounce(fn, 500);
    d.call("x");
    d.cancel();
    vi.advanceTimersByTime(1000);
    expect(fn).not.toHaveBeenCalled();
  });
});
