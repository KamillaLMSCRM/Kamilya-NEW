import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

describe("ConfirmDialog", () => {
  it("renders title and message", () => {
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Удалить курс?"
        message="Действие необратимо"
      />
    );
    expect(screen.getByText("Удалить курс?")).toBeInTheDocument();
    expect(screen.getByText("Действие необратимо")).toBeInTheDocument();
  });

  it("renders without message (title only)", () => {
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Только заголовок"
      />
    );
    expect(screen.getByText("Только заголовок")).toBeInTheDocument();
  });

  it("renders danger variant with red confirm button", () => {
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Delete"
        message="Delete this file"
        variant="danger"
        confirmLabel="Delete"
      />
    );
    const confirmBtn = screen.getByRole("button", { name: /^delete$/i });
    expect(confirmBtn).toBeInTheDocument();
    expect(confirmBtn.className).toContain("red-600");
  });

  it("renders warning variant with amber confirm button", () => {
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Warning"
        message="This may affect data"
        variant="warning"
        confirmLabel="Save"
      />
    );
    const confirmBtn = screen.getByRole("button", { name: /^save$/i });
    expect(confirmBtn.className).toContain("amber-600");
  });

  it("renders info variant with blue confirm button", () => {
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={vi.fn()}
        title="Info"
        message="Just so you know"
        variant="info"
        confirmLabel="OK"
      />
    );
    const confirmBtn = screen.getByRole("button", { name: /^ok$/i });
    expect(confirmBtn.className).toContain("blue-600");
  });

  it("calls onClose when cancel clicked (default label 'Отмена' from i18n)", () => {
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        open={true}
        onClose={onClose}
        onConfirm={vi.fn()}
        title="Confirm"
        message="Confirm message"
      />
    );
    fireEvent.click(screen.getByText("Отмена"));
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onConfirm when confirm clicked", async () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={onConfirm}
        title="Confirm"
        message="Confirm message"
        confirmLabel="Yes"
      />
    );
    fireEvent.click(screen.getByText("Yes"));
    await act(() => new Promise((r) => setTimeout(r, 10)));
    expect(onConfirm).toHaveBeenCalled();
  });

  it("shows loading state while confirming (button shows 'Сохранение...')", async () => {
    const onConfirm = vi.fn(
      () => new Promise<void>((resolve) => setTimeout(resolve, 200))
    );
    render(
      <ConfirmDialog
        open={true}
        onClose={vi.fn()}
        onConfirm={onConfirm}
        title="Long Confirm"
        message="This takes time"
        confirmLabel="OK"
      />
    );
    fireEvent.click(screen.getByText("OK"));
    // While promise is in flight, label changes to "Сохранение..."
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(screen.queryByText("OK")).not.toBeInTheDocument();
    expect(screen.getByText("Сохранение...")).toBeInTheDocument();
  });
});
