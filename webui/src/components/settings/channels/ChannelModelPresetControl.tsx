import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ModelPresetSelect } from "@/components/ModelPresetSelect";
import type { ModelPresetOption } from "@/lib/types";
import { cn } from "@/lib/utils";

export function ChannelModelPresetControl({
  value,
  options,
  saving = false,
  onSave,
  className,
}: {
  value?: string | null;
  options: readonly ModelPresetOption[];
  saving?: boolean;
  onSave: (name: string) => void;
  className?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3", className)}>
      <div className="min-w-0">
        <p className="text-[13px] font-semibold text-foreground">
          {t("settings.channels.defaultModel", { defaultValue: "Default model" })}
        </p>
        <p className="mt-0.5 text-[11.5px] leading-5 text-muted-foreground">
          {t("settings.channels.defaultModelHelp", {
            defaultValue: "Used when a conversation has no session override.",
          })}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" aria-hidden /> : null}
        <ModelPresetSelect
          aria-label={t("settings.channels.defaultModel", { defaultValue: "Default model" })}
          options={options}
          value={value}
          disabled={saving}
          onValueChange={onSave}
        />
      </div>
    </div>
  );
}
