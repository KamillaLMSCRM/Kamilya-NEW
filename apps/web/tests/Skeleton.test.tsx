import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"

import { Skeleton, CardSkeleton, TableSkeleton } from "@/components/ui/Skeleton"

describe("Skeleton", () => {
  it("renders with default variant", () => {
    render(<Skeleton />)
    const el = document.querySelector(".animate-pulse")
    expect(el).toBeInTheDocument()
  })

  it("renders circular variant", () => {
    render(<Skeleton variant="circular" />)
    const el = document.querySelector(".rounded-full")
    expect(el).toBeInTheDocument()
  })

  it("renders rectangular variant with width", () => {
    render(<Skeleton variant="rectangular" width="200px" />)
    const el = document.querySelector(".animate-pulse")
    expect(el).toBeInTheDocument()
    expect(el!.getAttribute("style")).toContain("200px")
  })

  it("accepts custom className", () => {
    render(<Skeleton className="custom-class" />)
    const el = document.querySelector(".custom-class")
    expect(el).toBeInTheDocument()
  })
})

describe("CardSkeleton", () => {
  it("renders skeleton card", () => {
    render(<CardSkeleton />)
    const skeletons = document.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })
})

describe("TableSkeleton", () => {
  it("renders skeleton rows", () => {
    render(<TableSkeleton rowCount={3} columns={4} />)
    const skeletons = document.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })
})
