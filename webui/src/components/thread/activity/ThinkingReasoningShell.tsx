import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode, Ref } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

const ACTIVITY_HEIGHT_KEY = "nanobot.activityResizeHeight";
const DEFAULT_ACTIVITY_HEIGHT = 180;
const MIN_ACTIVITY_HEIGHT = 120;
const MAX_ACTIVITY_HEIGHT = 560;

function clampHeight(value: number): number {
  return Math.min(MAX_ACTIVITY_HEIGHT, Math.max(MIN_ACTIVITY_HEIGHT, value));
}

function loadSavedHeight(): number {
  try {
    const raw = window.localStorage.getItem(ACTIVITY_HEIGHT_KEY);
    if (raw == null) return DEFAULT_ACTIVITY_HEIGHT;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? clampHeight(parsed) : DEFAULT_ACTIVITY_HEIGHT;
  } catch {
    return DEFAULT_ACTIVITY_HEIGHT;
  }
}

function saveHeight(value: number): void {
  try {
    window.localStorage.setItem(ACTIVITY_HEIGHT_KEY, String(value));
  } catch {
    // storage unavailable — the in-memory value still applies for this session
  }
}

interface ThinkingReasoningShellProps {
  active: boolean;
  expanded: boolean;
  label: string;
  /** Number of failed activity steps; shows a red badge next to the label. */
  errorCount?: number;
  children: ReactNode;
  viewportRef: Ref<HTMLDivElement>;
  contentRef: Ref<HTMLDivElement>;
  fadeTop: boolean;
  fadeBottom: boolean;
  onToggle: () => void;
  onScroll: () => void;
}

export function ThinkingReasoningShell({
  active,
  expanded,
  label,
  errorCount = 0,
  children,
  viewportRef,
  contentRef,
  fadeTop,
  fadeBottom,
  onToggle,
  onScroll,
}: ThinkingReasoningShellProps) {
  const { t } = useTranslation();
  const errorLabel = errorCount > 0
    ? t("message.activityFailedSuffix", {
        count: errorCount,
        defaultValue: "· {{count}} 失败",
      })
    : "";
  const [maxHeight, setMaxHeight] = useState<number>(() => loadSavedHeight());
  const maxHeightRef = useRef(maxHeight);
  const dragState = useRef<{ pointerId: number; startY: number; startHeight: number } | null>(null);

  useEffect(() => {
    maxHeightRef.current = maxHeight;
  }, [maxHeight]);

  const onResizePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragState.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startHeight: maxHeightRef.current,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const onResizePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragState.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    setMaxHeight(clampHeight(drag.startHeight + (event.clientY - drag.startY)));
  };

  const endResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragState.current || event.pointerId !== dragState.current.pointerId) return;
    dragState.current = null;
    saveHeight(maxHeightRef.current);
  };
  return (
    <div
      className="flex w-full max-w-[45rem] animate-in flex-col fade-in duration-300 motion-reduce:animate-none"
      data-state={active ? "thinking" : "done"}
    >
      <button
        type="button"
        data-thread-disclosure=""
        className="group inline-flex min-h-5 items-center self-start gap-1.5 bg-transparent p-0"
        onClick={onToggle}
        aria-expanded={expanded}
        aria-label={label}
        aria-live={active ? "polite" : undefined}
      >
        <span
          className={cn(
            "min-w-0 truncate text-[13px] font-medium leading-[18px] text-muted-foreground/70",
            active && "animate-pulse motion-reduce:animate-none",
          )}
        >
          {label}
        </span>
        {errorLabel ? (
          <span
            data-testid="activity-failure-badge"
            className="shrink-0 rounded-full bg-red-500/10 px-1.5 py-px text-[11px] font-semibold leading-[16px] text-red-500"
          >
            {errorLabel}
          </span>
        ) : null}
        <span
          className={cn(
            "inline-flex shrink-0 transition-transform [transition-duration:220ms] ease-out",
            "motion-reduce:transition-none",
            expanded && "rotate-180",
          )}
        >
          <ChevronDown
            className={cn(
              "h-3 w-3 text-muted-foreground/60 transition-colors duration-200",
              "group-hover:text-muted-foreground motion-reduce:transition-none",
            )}
            strokeWidth={1.8}
            aria-hidden
          />
        </span>
      </button>

      <div
        className={cn(
          "grid transition-[grid-template-rows,opacity] [transition-duration:220ms] ease-out motion-reduce:transition-none",
          expanded
            ? "grid-rows-[1fr] opacity-100"
            : "pointer-events-none grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="relative min-h-0 overflow-hidden">
          <div
            ref={viewportRef}
            data-testid={expanded ? "agent-activity-scroll" : undefined}
            data-fade-top={fadeTop}
            data-fade-bottom={fadeBottom}
            onScroll={onScroll}
            className="mt-1.5 overflow-y-auto pr-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            style={{ maxHeight }}
            aria-hidden={!expanded}
          >
            <div ref={contentRef} className="flex flex-col gap-0.5">
              {children}
            </div>
          </div>
          {fadeTop ? (
            <span
              data-testid="activity-scroll-fade-top"
              className="pointer-events-none absolute inset-x-0 top-1.5 z-10 h-3.5 bg-gradient-to-b from-background to-transparent"
              aria-hidden
            />
          ) : null}
          {fadeBottom ? (
            <span
              data-testid="activity-scroll-fade-bottom"
              className="pointer-events-none absolute inset-x-0 bottom-0 z-10 h-3.5 bg-gradient-to-t from-background to-transparent"
              aria-hidden
            />
          ) : null}
        </div>
      </div>
      {expanded ? (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label={t("message.activityResizeHandle", {
            defaultValue: "Resize height",
          })}
          data-testid="activity-resize-handle"
          onPointerDown={onResizePointerDown}
          onPointerMove={onResizePointerMove}
          onPointerUp={endResize}
          onPointerCancel={endResize}
          className="group/handle -mt-px flex h-3 cursor-ns-resize touch-none select-none items-center justify-center"
        >
          <span className="h-0.5 w-8 rounded-full bg-border transition-colors group-hover/handle:bg-muted-foreground/50" />
        </div>
      ) : null}
    </div>
  );
}
