import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"

import { ErrorPage, NotFoundPage, ServerErrorPage } from "@/components/ui/ErrorPage"

describe("ErrorPage", () => {
  let originalLocation: Location

  beforeEach(() => {
    originalLocation = window.location
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload: vi.fn() },
      writable: true,
      configurable: true,
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      value: originalLocation,
      writable: true,
      configurable: true,
    })
  })

  it("renders 404 error page", () => {
    render(<ErrorPage statusCode={404} title="Страница не найдена" message="Сообщение" />)
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument()
  })

  it("renders 500 error page", () => {
    render(<ErrorPage statusCode={500} title="Ошибка" message="Ошибка сервера" />)
    expect(screen.getByText("Ошибка")).toBeInTheDocument()
  })

  it("renders custom title and message", () => {
    render(<ErrorPage statusCode={400} title="Кастомный" message="Кастомное" />)
    expect(screen.getByText("Кастомный")).toBeInTheDocument()
    expect(screen.getByText("Кастомное")).toBeInTheDocument()
  })

  it("calls window.location.reload when refresh button clicked", () => {
    render(<ErrorPage statusCode={500} title="Ошибка" message="Ошибка сервера" />)
    fireEvent.click(screen.getByText("Обновить"))
    expect((window as any).location.reload).toHaveBeenCalled()
  })

  it("renders link to home page", () => {
    render(<ErrorPage statusCode={404} title="Ошибка" message="Ошибка" />)
    const link = screen.getByRole("link", { name: "На главную" })
    expect(link).toHaveAttribute("href", "/")
  })
})

describe("NotFoundPage", () => {
  it("renders 404 with specific heading", () => {
    render(<NotFoundPage />)
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument()
  })
})

describe("ServerErrorPage", () => {
  it("renders 500 with specific heading", () => {
    render(<ServerErrorPage />)
    expect(screen.getByText("Внутренняя ошибка сервера")).toBeInTheDocument()
  })
})
