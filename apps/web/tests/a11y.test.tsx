/**
 * Accessibility tests using axe-core.
 * Smoke-tests our shared UI primitives (Modal, ConfirmDialog, SkipToContent, Register, Sidebar).
 * Run via: pnpm test
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeAll } from "vitest";
import { axe, toHaveNoViolations } from "jest-axe";

// Register the axe matcher. Cast to any to avoid Vitest's static Assertion
// type — runtime extension works.
expect.extend(toHaveNoViolations as any);

// Top-level mocks (hoisted by Vitest)
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
}));

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

describe("Register form a11y", () => {
  // Mock fetch (the page does a public-register call)
  beforeAll(() => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    ) as any;
  });

  it("every input has an associated <label htmlFor>", async () => {
    const { default: RegisterPage } = await import("@/app/register-tenant/page");
    render(<RegisterPage />);
    const inputs = document.querySelectorAll("input");
    expect(inputs.length).toBeGreaterThan(0);
    inputs.forEach((input) => {
      const id = input.getAttribute("id");
      expect(id, "input must have id").toBeTruthy();
      const label = document.querySelector(`label[for="${id}"]`);
      expect(label, `label[for="${id}"] must exist`).not.toBeNull();
    });
  });

  it("required fields are marked with aria-required + visual asterisk", async () => {
    const { default: RegisterPage } = await import("@/app/register-tenant/page");
    render(<RegisterPage />);
    const required = document.querySelectorAll<HTMLInputElement>("input[required]");
    expect(required.length).toBeGreaterThan(0);
    required.forEach((input) => {
      expect(input.getAttribute("aria-required")).toBe("true");
      // Find a sibling <span aria-hidden="true">*</span> in the label
      const id = input.id;
      const label = document.querySelector(`label[for="${id}"]`);
      expect(label?.textContent).toMatch(/\*/);
    });
  });

  it("password field has aria-describedby pointing to a hint", async () => {
    const { default: RegisterPage } = await import("@/app/register-tenant/page");
    render(<RegisterPage />);
    const pw = document.getElementById("password") as HTMLInputElement;
    expect(pw).toBeTruthy();
    const describedBy = pw.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    const hint = document.getElementById(describedBy!);
    expect(hint).toBeTruthy();
    expect(hint?.textContent).toMatch(/8/);
  });

  it("renders a <main> landmark with id=main-content", async () => {
    const { default: RegisterPage } = await import("@/app/register-tenant/page");
    render(<RegisterPage />);
    const main = document.querySelector('main[id="main-content"]');
    expect(main).not.toBeNull();
  });
});

describe("Sidebar landmarks", () => {
  it("renders <nav> with aria-label and lists <ul role=list> items", async () => {
    // Mock useAuthStore (per-test because we need different state)
    vi.doMock("@/store/authStore", () => ({
      useAuthStore: (sel: any) =>
        sel({
          user: { role: "admin", full_name: "Test User" },
          logout: vi.fn(),
        }),
    }));

    const { default: Sidebar } = await import("@/components/layout/Sidebar");
    const { container } = render(<Sidebar collapsed={false} onToggle={() => {}} />);

    const nav = container.querySelector("nav");
    expect(nav).not.toBeNull();
    expect(nav?.getAttribute("aria-label")).toBeTruthy();

    // All nav items should be in <ul><li> structure
    const uls = container.querySelectorAll('nav ul[role="list"]');
    expect(uls.length).toBeGreaterThan(0);
    uls.forEach((ul) => {
      const lis = ul.querySelectorAll("li");
      expect(lis.length).toBeGreaterThan(0);
    });
  });

  it("collapse toggle has aria-expanded pointing to sidebar-nav", async () => {
    vi.doMock("@/store/authStore", () => ({
      useAuthStore: (sel: any) =>
        sel({
          user: { role: "admin", full_name: "Test User" },
          logout: vi.fn(),
        }),
    }));

    const { default: Sidebar } = await import("@/components/layout/Sidebar");
    const { container, rerender } = render(
      <Sidebar collapsed={false} onToggle={() => {}} />
    );
    const toggle = container.querySelector('button[aria-controls="sidebar-nav"]');
    expect(toggle).not.toBeNull();
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");

    rerender(<Sidebar collapsed={true} onToggle={() => {}} />);
    const toggle2 = container.querySelector('button[aria-controls="sidebar-nav"]');
    expect(toggle2?.getAttribute("aria-expanded")).toBe("false");
  });
});
