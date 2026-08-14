import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ThinkingReasoningShell } from "@/components/thread/activity/ThinkingReasoningShell";

const HEIGHT_KEY = "nanobot.activityResizeHeight";

function renderShell(expanded = true) {
  return render(
    <ThinkingReasoningShell
      active={false}
      expanded={expanded}
      label="已处理 2 步"
      viewportRef={undefined}
      contentRef={undefined}
      fadeTop={false}
      fadeBottom={false}
      onToggle={() => {}}
      onScroll={() => {}}
    >
      <div>process content</div>
    </ThinkingReasoningShell>,
  );
}

describe("ThinkingReasoningShell resize handle", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows a resize handle when expanded", () => {
    renderShell(true);
    expect(screen.getByTestId("activity-resize-handle")).toBeInTheDocument();
  });

  it("hides the resize handle when collapsed", () => {
    renderShell(false);
    expect(screen.queryByTestId("activity-resize-handle")).not.toBeInTheDocument();
  });

  it("grows the scrollport max-height when the handle is dragged down", () => {
    renderShell(true);
    const scrollport = screen.getByTestId("agent-activity-scroll");
    const handle = screen.getByTestId("activity-resize-handle");
    expect(scrollport).toHaveStyle({ maxHeight: "180px" });

    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 240 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 240 });

    expect(scrollport).toHaveStyle({ maxHeight: "320px" });
  });

  it("clamps the height within bounds and persists to localStorage", () => {
    renderShell(true);
    const scrollport = screen.getByTestId("agent-activity-scroll");
    const handle = screen.getByTestId("activity-resize-handle");

    fireEvent.pointerDown(handle, { pointerId: 1, clientY: 100 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientY: 100000 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientY: 100000 });

    expect(scrollport).toHaveStyle({ maxHeight: "560px" });
    expect(window.localStorage.getItem(HEIGHT_KEY)).toBe("560");
  });

  it("restores a previously saved height on mount", () => {
    window.localStorage.setItem(HEIGHT_KEY, "400");
    renderShell(true);
    expect(screen.getByTestId("agent-activity-scroll")).toHaveStyle({
      maxHeight: "400px",
    });
  });

  it("falls back to the default height for a corrupted saved value", () => {
    window.localStorage.setItem(HEIGHT_KEY, "not-a-number");
    renderShell(true);
    expect(screen.getByTestId("agent-activity-scroll")).toHaveStyle({
      maxHeight: "180px",
    });
  });
});
