import { providerDisplayLabel } from "@/lib/provider-brand";
import type { ModelPresetOption, SettingsPayload } from "@/lib/types";

export type ModelPresetCatalog = SettingsPayload["model_presets"];
export type ModelPresetCatalogItem = ModelPresetCatalog[number];

type ProviderCatalog = ReadonlyArray<{ name: string; label: string }>;

const GLOBAL_DEFAULT_NAME = "default";
const GLOBAL_DEFAULT_LABEL = "Use global default";

/**
 * Convert the gateway catalog into the stable option shape shared by Thread
 * and Channel Settings. The global default is always the first option, even
 * when an older gateway omits its catalog row.
 */
export function modelPresetOptionsFromCatalog(
  catalog: readonly ModelPresetCatalogItem[],
  modelCallOrder: readonly string[] = [],
  providers: ProviderCatalog = [],
): ModelPresetOption[] {
  const defaultPreset = catalog.find((preset) => preset.is_default);
  const options: ModelPresetOption[] = [
    toOption(defaultPreset, providers, {
      name: GLOBAL_DEFAULT_NAME,
      label: GLOBAL_DEFAULT_LABEL,
      isDefault: true,
    }),
  ];
  const order = new Map(
    modelCallOrder
      .map((name, index) => [name.trim(), index] as const)
      .filter(([name]) => name.length > 0),
  );
  const seen = new Set([GLOBAL_DEFAULT_NAME]);

  catalog
    .filter((preset) => !preset.is_default && preset.name.trim())
    .slice()
    .sort((left, right) => (
      (order.get(left.name.trim()) ?? Number.POSITIVE_INFINITY)
      - (order.get(right.name.trim()) ?? Number.POSITIVE_INFINITY)
    ))
    .forEach((preset) => {
      const name = preset.name.trim();
      if (seen.has(name)) return;
      seen.add(name);
      options.push(toOption(preset, providers, { name, label: preset.label?.trim() || name, isDefault: false }));
    });

  return options;
}

export function modelPresetOptionsFromSettings(
  settings: Pick<SettingsPayload, "model_presets" | "model_call_order" | "providers">,
): ModelPresetOption[] {
  return modelPresetOptionsFromCatalog(
    settings.model_presets,
    settings.model_call_order,
    settings.providers,
  );
}

/** Invalid or deleted persisted values inherit the global default safely. */
export function normalizeModelPresetName(
  value: string | null | undefined,
  options: readonly ModelPresetOption[],
): string {
  const requested = value?.trim();
  return requested && options.some((option) => option.name === requested && !option.disabled)
    ? requested
    : GLOBAL_DEFAULT_NAME;
}

function toOption(
  preset: ModelPresetCatalogItem | undefined,
  providers: ProviderCatalog,
  overrides: Pick<ModelPresetOption, "name" | "label"> & Partial<Pick<ModelPresetOption, "isDefault">>,
): ModelPresetOption {
  const provider = preset?.resolved_provider || preset?.provider || null;
  return {
    name: overrides.name,
    label: overrides.label,
    model: preset?.model ?? null,
    provider,
    providerLabel: providerDisplayLabel([...providers], provider) || provider,
    isDefault: overrides.isDefault ?? false,
    disabled: false,
  };
}

export { GLOBAL_DEFAULT_NAME };
