import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CompetenciesPage from "@/app/competencies/page";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const apiMock = vi.mocked(api);

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    accessToken: "test-token",
    initialized: true,
    user: {
      user_id: "methodologist-1",
      tenant_id: "tenant-1",
      tenant: { id: "tenant-1", name: "Test tenant" },
      telegram_id: "",
      role: "methodologist",
      roles: ["methodologist"],
      full_name: "Methodologist",
      email: "methodologist@example.com",
    },
  });
});

describe("Wave 2.2 qualification controls", () => {
  it("shows linked positions as read-only deep-links and preserves IDs on save", async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === "/v1/competencies")
        return {
          data: [{ id: "competency-1", name: "Safety", description: "", position_count: 1, course_count: 1 }],
        } as any;
      if (url === "/v1/positions") return { data: [{ id: "position-1", name: "Manager" }] } as any;
      if (url === "/v1/courses")
        return {
          data: [
            { id: "course-1", title: "Safety" },
            { id: "course-2", title: "Emergency" },
          ],
        } as any;
      if (url === "/v1/competencies/competency-1")
        return {
          data: {
            id: "competency-1",
            name: "Safety",
            description: "Required",
            position_count: 1,
            course_count: 1,
            position_ids: ["position-1"],
            course_ids: ["course-1"],
          },
        } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.patch.mockResolvedValue({ data: {} } as any);
    apiMock.put.mockResolvedValue({ data: {} } as any);

    render(<CompetenciesPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Safety/ }));

    expect(await screen.findByRole("link", { name: /Manager/ })).toHaveAttribute(
      "href",
      "/positions/position-1?tab=competencies",
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    fireEvent.click(screen.getByRole("button", { name: /Сохранить/ }));

    await waitFor(() =>
      expect(apiMock.put).toHaveBeenCalledWith("/v1/competencies/competency-1/links", {
        position_ids: ["position-1"],
        course_ids: ["course-1", "course-2"],
      }),
    );
  });
});
