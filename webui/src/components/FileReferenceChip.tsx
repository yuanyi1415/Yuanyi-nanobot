import type { KeyboardEvent, MouseEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface FileReferenceChipProps {
  path: string;
  tooltipPath?: string;
  display?: "name" | "path";
  active?: boolean;
  className?: string;
  textClassName?: string;
  previewPath?: string;
  unavailable?: boolean;
  onOpen?: (path: string) => void;
  testId?: string;
}

export function FileReferenceChip({
  path,
  tooltipPath,
  display = "name",
  active = false,
  className,
  textClassName,
  previewPath,
  unavailable = false,
  onOpen,
  testId = "inline-file-path",
}: FileReferenceChipProps) {
  const { t } = useTranslation();
  const { directory, name } = splitFilePath(path);
  const displayText = display === "path" ? path.replace(/\\/g, "/") : name;
  const fullPath = tooltipPath || path;
  const targetPath = previewPath || tooltipPath || path;
  const interactive = Boolean(onOpen);
  const openPreview = (event: MouseEvent | KeyboardEvent) => {
    if (!onOpen) return;
    event.preventDefault();
    event.stopPropagation();
    onOpen(targetPath);
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    openPreview(event);
  };
  return (
    <TooltipProvider delayDuration={500} skipDelayDuration={100}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn("not-prose inline-flex max-w-full align-baseline leading-[inherit]", className)}
          >
            <span
              data-testid={testId}
              aria-label={fullPath}
              title={unavailable
                ? t("fileReference.unavailable", {
                    defaultValue: "File no longer available",
                  })
                : undefined}
              role={interactive ? "button" : undefined}
              tabIndex={interactive ? 0 : undefined}
              onClick={interactive ? openPreview : undefined}
              onKeyDown={interactive ? onKeyDown : undefined}
              className={cn(
                "inline-flex max-w-full items-baseline gap-[0.22em] font-[550] leading-[inherit]",
                "rounded-[3px] px-px text-[#2563eb] dark:text-[#7ab7ff]",
                interactive && [
                  "cursor-pointer",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[rgba(37,99,235,0.45)]",
                  "dark:focus-visible:ring-[rgba(122,183,255,0.5)]",
                ],
                unavailable && [
                  "cursor-not-allowed text-muted-foreground/65 dark:text-muted-foreground/65",
                ],
              )}
            >
              <FileReferenceIcon />
              <span
                data-sheen-text={active ? displayText : undefined}
                className={cn(
                  "min-w-0 max-w-full [overflow-wrap:anywhere] sm:truncate",
                  active && "streaming-text-sheen file-reference-sheen",
                  textClassName,
                )}
              >
                {display === "path" && directory ? (
                  <>
                    <span className="min-w-0 opacity-70">{directory}</span>
                    <span className="font-semibold">{name}</span>
                  </>
                ) : (
                  displayText
                )}
              </span>
            </span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          align="center"
          sideOffset={8}
          collisionPadding={12}
          className={cn(
            "max-w-[min(38rem,calc(100vw-2rem))] rounded-[10px]",
            "px-2.5 py-1.5",
            "break-all font-mono text-[11px] leading-snug text-popover-foreground",
          )}
        >
          {fullPath}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

export function isLikelyFilePath(value: string): boolean {
  const raw = value.trim();
  if (!raw || raw.includes("\n")) return false;
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(raw)) return false;
  if (isFilePatternReference(raw)) return false;
  if (!/[\\/]/.test(raw) && !/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(raw)) {
    return false;
  }
  const normalized = raw.replace(/\\/g, "/");
  const name = normalized.split("/").filter(Boolean).pop() ?? normalized;
  if (!name || name === "." || name === "..") return false;
  if (/^(dockerfile|makefile|readme|package-lock\.json)$/i.test(name)) return true;
  return /\.[a-z0-9][a-z0-9_-]{0,12}$/i.test(name);
}

export function isFilePatternReference(value: string): boolean {
  return /[*?[\]{}]/.test(value.trim());
}

export function splitFilePath(path: string): { directory: string; name: string } {
  const normalized = path.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return { directory: "", name: path };
  return {
    directory: normalized.slice(0, slash + 1),
    name: normalized.slice(slash + 1) || normalized,
  };
}

export function FileReferenceIcon() {
  return (
    <svg
      aria-hidden
      className="h-[0.95em] w-[0.95em] shrink-0 translate-y-[0.12em]"
      viewBox="0 0 1024 1024"
      fill="none"
    >
      <path
        d="M684.8 874.666667H241.066667c-44.8 0-81.066667-36.266667-81.066667-81.066667V230.4C160 185.6 196.266667 149.333333 241.066667 149.333333H499.2c14.933333 0 32 4.266667 44.8 12.8l185.6 123.733334c23.466667 14.933333 36.266667 40.533333 36.266667 66.133333v439.466667c-2.133333 46.933333-38.4 83.2-81.066667 83.2z"
        fill="#2953FF"
      />
      <path
        d="M778.666667 695.466667H465.066667c-46.933333 0-85.333333-38.4-85.333334-85.333334v-110.933333c0-46.933333 38.4-85.333333 85.333334-85.333333h313.6c46.933333 0 85.333333 38.4 85.333333 85.333333v110.933333c0 46.933333-38.4 85.333333-85.333333 85.333334z"
        fill="#FCCA1E"
      />
    </svg>
  );
}
