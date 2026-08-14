import { MessageSquareText } from "lucide-react";

import { ActivityStep } from "./ActivityStep";

/**
 * Intermediate body text folded into a completed activity unit ("process text").
 * Rendered inside 已处理 so the terminal view stays [fold] + [final answer]
 * while the intermediate narration stays inspectable on expand.
 */
export function ProcessTextRow({ text, className }: { text: string; className?: string }) {
  const preview = text.trim();
  return (
    <ActivityStep
      marker={
        <MessageSquareText
          data-testid="activity-process-text-marker"
          className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40"
          strokeWidth={1.8}
          aria-hidden
        />
      }
      active={false}
      tone="neutral"
      label={preview}
      labelClassName="text-muted-foreground/70"
      contentClassName="overflow-hidden"
      className={className}
    />
  );
}
