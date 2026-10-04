/** Trailing-edge debounce (transition comment PATCHes). */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): { call: (...args: A) => void; cancel: () => void; flush: () => void } {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pending: A | null = null;
  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    pending = null;
  };
  const flush = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    if (pending !== null) {
      const args = pending;
      pending = null;
      fn(...args);
    }
  };
  const call = (...args: A) => {
    pending = args;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(flush, ms);
  };
  return { call, cancel, flush };
}
