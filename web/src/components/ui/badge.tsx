import * as React from "react";
import { cn } from "../../lib/utils";

export function Badge({
  className,
  style,
  ...props
}: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-semibold",
        className,
      )}
      style={style}
      {...props}
    />
  );
}
