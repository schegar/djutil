import { camelotColor } from "../lib/camelot";
import { cn } from "../lib/utils";

/** Camelot key multi-select rendered as a 12xA/B grid with standard colours. */
export function CamelotWheel({
  selected,
  counts,
  onChange,
}: {
  selected: string[];
  counts?: Record<string, number>;
  onChange: (v: string[]) => void;
}) {
  function toggle(k: string) {
    onChange(
      selected.includes(k)
        ? selected.filter((s) => s !== k)
        : [...selected, k],
    );
  }
  return (
    <div className="grid grid-cols-6 gap-1">
      {Array.from({ length: 24 }, (_, i) => {
        const num = (i % 12) + 1;
        const letter = i < 12 ? "A" : "B";
        const key = `${num}${letter}`;
        const active = selected.includes(key);
        const count = counts?.[key];
        return (
          <button
            key={key}
            type="button"
            onClick={() => toggle(key)}
            title={count != null ? `${key} — ${count} tracks` : key}
            className={cn(
              "relative flex h-8 items-center justify-center rounded text-xs font-bold text-black transition-transform",
              active
                ? "ring-2 ring-white ring-offset-1 ring-offset-neutral-950"
                : "opacity-60 hover:opacity-100",
              count === 0 && "opacity-25",
            )}
            style={{ backgroundColor: camelotColor(key) }}
          >
            {key}
          </button>
        );
      })}
    </div>
  );
}
