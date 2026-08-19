import { useLayoutEffect, useRef, useState } from "react";
import { CircleHelp, ChevronDown, Sparkles, Check, RotateCcw } from "lucide-react";

import { useLogoFallback } from "@/hooks/useLogoFallback";
import { inferProviderFromModelName, providerBrand } from "@/lib/provider-brand";
import type { ModelPresetOption as SharedModelPresetOption } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The thread accepts partial catalog rows so it remains easy to use in tests and hosts. */
export type ModelPresetOption = Pick<SharedModelPresetOption, "name" | "label"> &
  Partial<Omit<SharedModelPresetOption, "name" | "label">>;

interface ModelPresetBadgeProps {
  label: string;
  modelDetail?: string | null;
  modelPreset?: string | null;
  modelPresets?: ModelPresetOption[];
  onPresetChange?: (name: string) => void;
  provider?: string | null;
  providerLabel?: string | null;
  needsSetup?: boolean;
  fallbackModelName?: string | null;
  isHero: boolean;
  onClick?: () => void;
  /** True when the displayed effective model comes from this Session's override. */
  modelPresetIsOverride?: boolean;
}

export function ModelPresetBadge({
  label,
  modelDetail,
  modelPreset,
  modelPresets = [],
  onPresetChange,
  provider,
  providerLabel,
  needsSetup = false,
  fallbackModelName,
  isHero,
  onClick,
  modelPresetIsOverride = false,
}: ModelPresetBadgeProps) {
  const activeName = modelPreset?.trim() || "default";
  const selectOptions: SharedModelPresetOption[] = [
    {
      name: "default",
      label: "Use global default",
      model: null,
      provider: null,
      providerLabel: null,
      isDefault: true,
      disabled: false,
    },
    ...modelPresets
      .filter((preset) => preset.name !== "default")
      .map((preset) => ({
        name: preset.name,
        label: preset.label || preset.name,
        model: preset.model ?? null,
        provider: preset.provider ?? null,
        providerLabel: preset.providerLabel ?? null,
        isDefault: false,
        disabled: preset.disabled ?? false,
      })),
  ];
  const hasSelection = Boolean(onPresetChange) && selectOptions.length > 1;
  const interactive = Boolean(onClick) && !hasSelection;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close menu when clicking outside
  useLayoutEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  const handleChange = (name: string) => {
    onPresetChange?.(name);
    setMenuOpen(false);
  };

  const badge = (
    <span
      data-testid="composer-model-badge"
      data-model-selection={modelPresetIsOverride ? "session-override" : "global-default"}
      data-selectable={hasSelection ? "true" : undefined}
      className="relative inline-flex w-fit"
      ref={menuRef}
    >
      <button
        ref={buttonRef}
        type="button"
        data-fallback={fallbackModelName ? "true" : undefined}
        disabled={!hasSelection && !interactive}
        onClick={hasSelection ? () => setMenuOpen(!menuOpen) : onClick}
        className={cn(
          "composer-model-badge group/badge flex items-center gap-1.5 rounded-full transition-all duration-150",
          "border border-border/60 bg-background/80 backdrop-blur-sm",
          "hover:border-border hover:bg-background hover:shadow-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-1",
          isHero ? "h-7 pl-1.5 pr-2 text-xs" : "h-8 pl-2 pr-2.5 text-[13px]",
          hasSelection && "cursor-pointer",
          !hasSelection && !interactive && "cursor-default",
          needsSetup && "border-amber-400/40 bg-amber-50/50 hover:bg-amber-50/80 dark:border-amber-500/30 dark:bg-amber-950/20",
          modelPresetIsOverride && !needsSetup && "border-primary/20 bg-primary/5",
        )}
        title={fallbackModelName || [...new Set([label, modelDetail, providerLabel].filter(Boolean))].join(" · ")}
      >
        {/* Provider icon */}
        <PresetIcon
          provider={provider}
          needsSetup={needsSetup}
          label={label}
          modelDetail={modelDetail}
          isHero={isHero}
        />
        {/* Label */}
        <span className={cn(
          "font-medium text-foreground/80 group-hover/badge:text-foreground transition-colors",
          "max-w-[140px] truncate",
        )}>
          {label}
        </span>
        {/* Override indicator */}
        {modelPresetIsOverride && (
          <span
            className="h-1.5 w-1.5 rounded-full bg-primary shrink-0"
            title="Session override active"
          />
        )}
        {/* Dropdown chevron */}
        {hasSelection && (
          <ChevronDown
            className={cn(
              "h-3 w-3 text-foreground/40 transition-transform duration-200 shrink-0",
              menuOpen && "rotate-180 text-foreground/60",
            )}
          />
        )}
      </button>

      {/* Dropdown menu */}
      {hasSelection && menuOpen && (
        <>
          {/* Backdrop for click-outside */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setMenuOpen(false)}
          />
          {/* Menu */}
          <div
            className={cn(
              "absolute z-50 mt-1.5 min-w-[220px] max-w-[280px]",
              "overflow-hidden rounded-xl border border-border/50",
              "bg-popover/95 backdrop-blur-md shadow-lg shadow-black/5",
              "animate-in fade-in-0 zoom-in-95 slide-in-from-top-1 duration-150",
              "right-0",
            )}
            data-testid="model-preset-menu"
          >
            {/* Header */}
            <div className="px-3 py-2 border-b border-border/30">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
                Switch model
              </span>
            </div>
            {/* Options */}
            <div className="p-1 max-h-[300px] overflow-y-auto">
              {selectOptions.map((option) => {
                const isSelected = option.name === activeName;
                const brand = option.provider ? providerBrand(option.provider) : null;
                const isDefaultOption = option.name === "default";
                return (
                  <button
                    key={option.name}
                    type="button"
                    disabled={option.disabled}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleChange(option.name);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all duration-100",
                      "hover:bg-accent hover:text-accent-foreground",
                      "disabled:cursor-not-allowed disabled:opacity-40",
                      "focus-visible:outline-none focus-visible:bg-accent",
                      isSelected && "bg-accent/60",
                    )}
                  >
                    {/* Icon */}
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center">
                      {isSelected ? (
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10">
                          <Check className="h-3 w-3 text-primary" strokeWidth={2.5} />
                        </span>
                      ) : isDefaultOption ? (
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted">
                          <RotateCcw className="h-3 w-3 text-muted-foreground" />
                        </span>
                      ) : brand ? (
                        <span
                          className="grid h-5 w-5 place-items-center rounded-full text-[8px] font-bold text-white shadow-sm"
                          style={{ backgroundColor: brand.color }}
                        >
                          {brand.initials.slice(0, 2)}
                        </span>
                      ) : (
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted">
                          <Sparkles className="h-3 w-3 text-muted-foreground/60" />
                        </span>
                      )}
                    </span>
                    {/* Text */}
                    <span className="flex flex-col items-start min-w-0 flex-1">
                      <span className={cn(
                        "truncate w-full",
                        isSelected ? "font-medium text-foreground" : "text-foreground/90",
                      )}>
                        {option.label}
                      </span>
                      {option.providerLabel && !isDefaultOption && (
                        <span className="text-[11px] text-muted-foreground truncate w-full">
                          {option.providerLabel}
                        </span>
                      )}
                      {isDefaultOption && (
                        <span className="text-[11px] text-muted-foreground/70">
                          Follow global setting
                        </span>
                      )}
                    </span>
                    {/* Override badge */}
                    {isSelected && modelPresetIsOverride && !isDefaultOption && (
                      <span className="shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        Session
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </span>
  );

  if (interactive) {
    return badge;
  }
  return badge;
}

function PresetIcon({
  provider,
  needsSetup = false,
  label,
  modelDetail,
  isHero,
}: {
  provider?: string | null;
  needsSetup?: boolean;
  label: string;
  modelDetail?: string | null;
  isHero: boolean;
}) {
  const inferredProvider = needsSetup
    ? null
    : provider || inferProviderFromModelName(modelDetail || label);
  const brand = providerBrand(inferredProvider);
  const { logoUrl, onLogoError, onLogoLoad } = useLogoFallback(brand?.logoUrls);
  const size = isHero ? "h-4 w-4" : "h-[18px] w-[18px]";

  if (needsSetup) {
    return (
      <span data-testid="composer-model-setup-icon" className={cn("grid shrink-0 place-items-center rounded-full bg-amber-100 dark:bg-amber-900/30", size)}>
        <CircleHelp className={cn("text-amber-700 dark:text-amber-300", isHero ? "h-3 w-3" : "h-3.5 w-3.5")} strokeWidth={1.8} />
      </span>
    );
  }

  if (logoUrl) {
    return (
      <span data-testid={inferredProvider ? `composer-model-logo-${inferredProvider}` : "composer-model-logo"} className={cn("grid shrink-0 place-items-center overflow-hidden rounded-full border border-border/40 bg-background", size)}>
        <img
          src={logoUrl}
          alt=""
          draggable={false}
          decoding="async"
          loading="lazy"
          className={cn("object-contain", isHero ? "h-3 w-3" : "h-3.5 w-3.5")}
          onLoad={onLogoLoad}
          onError={onLogoError}
        />
      </span>
    );
  }

  if (brand) {
    return (
      <span
        data-testid={inferredProvider ? `composer-model-logo-${inferredProvider}` : "composer-model-logo"}
        className={cn("grid shrink-0 place-items-center rounded-full text-white font-bold shadow-sm", size, isHero ? "text-[7px]" : "text-[8px]")}
        style={{ backgroundColor: brand.color }}
      >
        {brand.initials.slice(0, 2)}
      </span>
    );
  }

  return (
    <span data-testid="composer-model-logo" className={cn("grid shrink-0 place-items-center rounded-full bg-muted", size)}>
      <Sparkles className={cn("text-muted-foreground/60", isHero ? "h-3 w-3" : "h-3.5 w-3.5")} />
    </span>
  );
}
