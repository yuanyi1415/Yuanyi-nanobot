import { describe, expect, it } from "vitest";

import {
  modelPresetOptionsFromCatalog,
  normalizeModelPresetName,
} from "@/lib/model-presets";

const catalog = [
  {
    name: "slow",
    label: "Slow",
    active: false,
    is_default: false,
    model: "vendor/slow",
    provider: "openai_codex",
    resolved_provider: "openai",
    max_tokens: 100,
    context_window_tokens: 1000,
    temperature: 0,
    reasoning_effort: null,
  },
  {
    name: "default",
    label: "Default",
    active: true,
    is_default: true,
    model: "vendor/default",
    provider: "openai",
    resolved_provider: "openai",
    max_tokens: 100,
    context_window_tokens: 1000,
    temperature: 0,
    reasoning_effort: null,
  },
  {
    name: "fast",
    label: "Fast",
    active: false,
    is_default: false,
    model: "vendor/fast",
    provider: "anthropic",
    resolved_provider: "anthropic",
    max_tokens: 100,
    context_window_tokens: 1000,
    temperature: 0,
    reasoning_effort: null,
  },
];

describe("model preset options", () => {
  it("WHEN a catalog and call order are provided SHOULD put the global default first and preserve the order", () => {
    const options = modelPresetOptionsFromCatalog(catalog, ["fast", "slow"], [
      { name: "anthropic", label: "Anthropic" },
      { name: "openai", label: "OpenAI" },
    ]);

    expect(options.map((option) => option.name)).toEqual(["default", "fast", "slow"]);
    expect(options[0]).toMatchObject({
      label: "Use global default",
      providerLabel: "OpenAI",
      isDefault: true,
    });
    expect(options[1]).toMatchObject({ provider: "anthropic", providerLabel: "Anthropic" });
  });

  it("WHEN a persisted preset no longer exists SHOULD normalize it to the global default", () => {
    const options = modelPresetOptionsFromCatalog(catalog);

    expect(normalizeModelPresetName("deleted-preset", options)).toBe("default");
    expect(normalizeModelPresetName(" fast ", options)).toBe("fast");
  });

  it("WHEN the catalog omits its default row SHOULD still expose a usable default option", () => {
    const options = modelPresetOptionsFromCatalog(catalog.filter((preset) => !preset.is_default));

    expect(options[0]).toMatchObject({ name: "default", label: "Use global default" });
    expect(normalizeModelPresetName(null, options)).toBe("default");
  });
});
