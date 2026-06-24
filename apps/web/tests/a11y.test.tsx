/**
 * Accessibility tests using axe-core.
 * Smoke-tests our shared UI primitives (Modal, ConfirmDialog, SkipToContent).
 * Run via: pnpm test
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { axe, toHaveNoViolations } from "jest-axe";

// Register the axe matcher. Cast to any to avoid Vitest's static Assertion
// type — runtime extension works.
expect.extend(toHaveNoViolations as any);

import { Modal } from "@/components/ui/modal";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { SkipToContent } from "@/components/a11y/SkipToContent";

describe("Modal a11y", () => {
  it("renders with role=dialog, aria-modal=true, and aria-labelledby", () => {
    render(
      <Modal open={true} onClose={() => {}} title="Test dialog">
        <p>Body</p>
      </Modal>
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-labelledby");
  });

  it("axe-core: passes WCAG 2.1 AA on a basic open modal", async () => {
    const { container } = render(
      <Modal open={true} onClose={() => {}} title="A11y modal">
        <p>Modal content</p>
        <button>OK</button>
      </Modal>
    );
    const results = await axe(container, {
      rules: { region: { enabled: false } }, // single dialogs don't need a region wrapper
    });
    (expect(results) as any).toHaveNoViolations();
  });

  it("closes on ESC keypress", () => {
    const onClose = vi.fn();
    render(
      <Modal open={true} onClose={onClose} title="ESC test">
        <p>x</p>
      </Modal>
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("does NOT close on ESC when dismissable=false", () => {
    const onClose = vi.fn();
    render(
      <Modal open={true} onClose={onClose} title="Locked" dismissable={false}>
        <p>x</p>
      </Modal>
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("registers a keydown handler while open (focus trap plumbing)", () => {
    const addSpy = vi.spyOn(document, "addEventListener");
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(
      <Modal open={true} onClose={() => {}} title="Trap test">
        <button>First</button>
        <button>Last</button>
      </Modal>
    );
    expect(addSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
    unmount();
    expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  });
});

describe("ConfirmDialog a11y", () => {
  it("axe-core: passes WCAG 2.1 AA on a confirm dialog", async () => {
    const { container } = render(
      <ConfirmDialog
        open={true}
        onClose={() => {}}
        onConfirm={() => {}}
        title="Delete course?"
        message="This action cannot be undone."
        confirmLabel="Delete"
      />
    );
    const results = await axe(container, {
      rules: { region: { enabled: false } },
    });
    (expect(results) as any).toHaveNoViolations();
  });
});

describe("SkipToContent a11y", () => {
  it("is present in the DOM with the correct href", () => {
    render(<SkipToContent />);
    // The text comes from i18n; just verify the link is present.
    const link = document.querySelector('a[href="#main-content"]');
    expect(link).not.toBeNull();
    expect(link).toHaveAttribute("href", "#main-content");
  });
});
