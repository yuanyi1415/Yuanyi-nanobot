import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkspaceProjectPicker } from "@/components/thread/WorkspaceControls";
import { ClientProvider } from "@/providers/ClientProvider";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { WorkspaceScopePayload, WorkspacesPayload } from "@/lib/types";

const DEFAULT_SCOPE: WorkspaceScopePayload = {
  project_path: "/Users/me",
  project_name: "me",
  access_mode: "restricted",
  restrict_to_workspace: true,
};

const CONTROLS: WorkspacesPayload["controls"] = {
  can_change_project: true,
  can_use_full_access: true,
};

function setHostname(hostname: string) {
  const original = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...original, hostname },
  });
  return () => {
    Object.defineProperty(window, "location", { configurable: true, value: original });
  };
}

function stubFetchJson(result: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, json: async () => result }),
  );
}

function renderPicker() {
  const onChange = vi.fn();
  const utils = render(
    <ClientProvider client={{} as NanobotClient} token="tok">
      <WorkspaceProjectPicker
        isHero
        scope={null}
        defaultScope={DEFAULT_SCOPE}
        controls={CONTROLS}
        onChange={onChange}
      />
    </ClientProvider>,
  );
  return { onChange, ...utils };
}

async function openPickerPopover() {
  fireEvent.click(screen.getByRole("button", { name: "Choose project" }));
  await screen.findByRole("button", { name: "Use Path" });
}

describe("WorkspaceProjectPicker directory browse button", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Browse button for loopback hosts", async () => {
    const restore = setHostname("localhost");
    try {
      renderPicker();
      await openPickerPopover();

      expect(screen.getByRole("button", { name: "Browse…" })).toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it("hides the Browse button for remote hosts", async () => {
    const restore = setHostname("nanobot.example.com");
    try {
      renderPicker();
      await openPickerPopover();

      expect(screen.queryByRole("button", { name: "Browse…" })).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });

  it("applies the picked folder path", async () => {
    const restore = setHostname("localhost");
    try {
      stubFetchJson({ path: "/Users/me/Desktop" });
      const { onChange } = renderPicker();
      await openPickerPopover();

      fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

      await waitFor(() => {
        expect(onChange).toHaveBeenCalledWith(
          expect.objectContaining({ project_path: "/Users/me/Desktop" }),
        );
      });
    } finally {
      restore();
    }
  });

  it("silently ignores cancellation", async () => {
    const restore = setHostname("localhost");
    try {
      stubFetchJson({ cancelled: true });
      const { onChange } = renderPicker();
      await openPickerPopover();

      fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Browse…" })).not.toBeDisabled();
      });
      expect(onChange).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });

  it("clears the selected project via the clear button", async () => {
    const restore = setHostname("localhost");
    try {
      const onChange = vi.fn();
      render(
        <ClientProvider client={{} as NanobotClient} token="tok">
          <WorkspaceProjectPicker
            isHero
            scope={{
              project_path: "/Users/me/Desktop",
              project_name: "Desktop",
              access_mode: "restricted",
              restrict_to_workspace: true,
            }}
            defaultScope={DEFAULT_SCOPE}
            controls={CONTROLS}
            onChange={onChange}
          />
        </ClientProvider>,
      );

      fireEvent.click(screen.getByRole("button", { name: "Clear project" }));

      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ project_path: "", project_name: "" }),
      );
    } finally {
      restore();
    }
  });

  it("does not spawn another dialog when the parent re-renders", async () => {
    const restore = setHostname("localhost");
    try {
      const fetchMock = vi
        .fn()
        .mockResolvedValue({ ok: true, json: async () => ({ cancelled: true }) });
      vi.stubGlobal("fetch", fetchMock);
      const { rerender } = renderPicker();
      await openPickerPopover();

      fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

      // Parent re-renders (scope changed) while the picker is mounted;
      // the picker effect must NOT re-run and spawn a second dialog.
      rerender(
        <ClientProvider client={{} as NanobotClient} token="tok">
          <WorkspaceProjectPicker
            isHero
            scope={{
              project_path: "/Users/me/Other",
              project_name: "Other",
              access_mode: "restricted",
              restrict_to_workspace: true,
            }}
            defaultScope={DEFAULT_SCOPE}
            controls={CONTROLS}
            onChange={() => {}}
          />
        </ClientProvider>,
      );

      await waitFor(() => {
        expect(fetchMock).toHaveBeenCalledTimes(1);
      });
    } finally {
      restore();
    }
  });

  it("shows a readable error when the picker fails", async () => {
    const restore = setHostname("localhost");
    try {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 500,
          headers: new Headers(),
          text: async () => "folder picker failed",
        }),
      );
      renderPicker();
      await openPickerPopover();

      fireEvent.click(screen.getByRole("button", { name: "Browse…" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("folder picker failed");
    } finally {
      restore();
    }
  });
});
