import { render, screen, fireEvent, act } from "@testing-library/react"
import { describe, it, expect, vi } from "vitest"

import { ConfirmDialog, ModalDialog } from "@/components/ui/ConfirmDialog"

describe("ModalDialog", () => {
  it("renders nothing when closed", () => {
    render(<ModalDialog open={false} title="Test"><p>Content</p></ModalDialog>)
    expect(screen.queryByText("Test")).not.toBeInTheDocument()
  })

  it("renders open modal with title and children", () => {
    render(<ModalDialog open={true} title="My Modal"><p>Content</p></ModalDialog>)
    expect(screen.getByText("My Modal")).toBeInTheDocument()
    expect(screen.getByText("Content")).toBeInTheDocument()
  })

  it("calls onClose when X button clicked", () => {
    const onClose = vi.fn()
    render(<ModalDialog open={true} onClose={onClose} title="Close Test"><p>Children</p></ModalDialog>)
    fireEvent.click(screen.getByLabelText("Close"))
    expect(onClose).toHaveBeenCalled()
  })

  it("renders backdrop overlay", () => {
    render(<ModalDialog open={true} onClose={vi.fn()} title="Backdrop Test"><p>Children</p></ModalDialog>)
    const backdrops = document.querySelectorAll('[aria-hidden="true"]')
    expect(backdrops.length).toBeGreaterThan(0)
  })
})

describe("ConfirmDialog", () => {
  it("renders close button", () => {
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={vi.fn()} title="Delete?" message="Are you sure?" />)
    expect(screen.getByText("Delete?")).toBeInTheDocument()
    expect(screen.getByText("Are you sure?")).toBeInTheDocument()
  })

  it("renders danger variant with red confirm button", () => {
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={vi.fn()} title="Delete" message="Delete this file" variant="danger" confirmText="Delete" />)
    const confirmBtn = screen.getByRole("button", { name: /delete/i })
    expect(confirmBtn).toBeInTheDocument()
    expect(confirmBtn.className).toContain("red-600")
  })

  it("renders warning variant with amber confirm button", () => {
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={vi.fn()} title="Warning" message="This may affect data" variant="warning" confirmText="Save" />)
    const confirmBtn = screen.getByRole("button", { name: /save/i })
    expect(confirmBtn).toBeInTheDocument()
    expect(confirmBtn.className).toContain("amber-600")
  })

  it("renders cancel button with default text", () => {
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={vi.fn()} title="Question" message="Are you sure?" />)
    expect(screen.getByText("Отмена")).toBeInTheDocument()
  })

  it("calls onClose when cancel clicked", () => {
    const onClose = vi.fn()
    render(<ConfirmDialog open={true} onClose={onClose} onConfirm={vi.fn()} title="Confirm" message="Confirm message" />)
    fireEvent.click(screen.getByText("Отмена"))
    expect(onClose).toHaveBeenCalled()
  })

  it("calls onConfirm when confirm clicked", async () => {
    const onConfirm = vi.fn()
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={onConfirm} title="Confirm" message="Confirm message" />)
    fireEvent.click(screen.getByText("OK"))
    await act(() => new Promise(r => setTimeout(r, 10)))
    expect(onConfirm).toHaveBeenCalled()
  })

  it("shows loading state while confirming", async () => {
    const onConfirm = vi.fn(() => new Promise<void>((resolve) => setTimeout(resolve, 200)))
    render(<ConfirmDialog open={true} onClose={vi.fn()} onConfirm={onConfirm} title="Long Confirm" message="This takes time" />)
    fireEvent.click(screen.getByText("OK"))
    await act(() => new Promise(r => setTimeout(r, 10)))
    expect(screen.queryByText("OK")).not.toBeInTheDocument()
    expect(screen.getByText("...")).toBeInTheDocument()
  })
})
