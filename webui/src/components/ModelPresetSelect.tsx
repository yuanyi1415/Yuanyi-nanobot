import { ChevronDown } from "lucide-react";
import type { SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";
import {
  GLOBAL_DEFAULT_NAME,
  normalizeModelPresetName,
} from "@/lib/model-presets";
import type { ModelPresetOption } from "@/lib/types";

export interface ModelPresetSelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value"> {
  options: readonly ModelPresetOption[];
  value?: string | null;
  onValueChange: (name: string) => void;
  /** Text used when a stale preset is normalized to the global default. */
  defaultLabel?: string;
}

/**
 * Shared native select for Model Presets. Native select is intentional here:
 * it gives Thread and Settings identical keyboard, touch, and screen-reader
 * behavior without maintaining a second menu state machine.
 */
export function ModelPresetSelect({
  options,
  value,
  onValueChange,
  defaultLabel = "Use global default",
  className,
  disabled,
  ...props
}: ModelPresetSelectProps) {
  const safeOptions = options.length > 0
    ? options
    : [{
      name: GLOBAL_DEFAULT_NAME,
      label: defaultLabel,
      model: null,
      provider: null,
      providerLabel: null,
      isDefault: true,
      disabled: false,
    } satisfies ModelPresetOption];
  const safeValue = normalizeModelPresetName(value, safeOptions);

  return (
    <span className="relative inline-flex min-w-0 items-center">
      <select
        {...props}
        value={safeValue}
        disabled={disabled}
        onChange={(event) => onValueChange(event.target.value)}
        className={cn(
          "h-9 min-w-0 appearance-none rounded-md border border-border bg-background py-1.5 pl-3 pr-8 text-sm text-foreground outline-none transition-colors",
          "hover:border-foreground/30 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/35",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
      >
        {safeOptions.map((option) => (
          <option key={option.name} value={option.name} disabled={option.disabled}>
            {option.label}
            {option.providerLabel ? ` · ${option.providerLabel}` : ""}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2 h-4 w-4 text-muted-foreground"
      />
    </span>
  );
}
