import * as SliderPrimitive from "@radix-ui/react-slider";
import { cn } from "../../lib/utils";

export function RangeSlider({
  className,
  value,
  onValueChange,
  min = 0,
  max = 200,
  step = 1,
}: {
  className?: string;
  value: [number, number];
  onValueChange: (v: [number, number]) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <SliderPrimitive.Root
      className={cn(
        "relative flex h-5 w-full touch-none select-none items-center",
        className,
      )}
      value={value}
      onValueChange={(v) => onValueChange(v as [number, number])}
      min={min}
      max={max}
      step={step}
      minStepsBetweenThumbs={1}
    >
      <SliderPrimitive.Track className="relative h-1 w-full rounded bg-neutral-800">
        <SliderPrimitive.Range className="absolute h-full rounded bg-neutral-300" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full bg-neutral-100 focus:outline-none" />
      <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full bg-neutral-100 focus:outline-none" />
    </SliderPrimitive.Root>
  );
}
