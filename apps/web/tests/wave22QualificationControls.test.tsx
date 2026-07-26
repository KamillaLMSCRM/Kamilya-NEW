import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RulesTab from "@/app/admin/staff/_tabs/RulesTab";
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
  it("does not locally grant rules or competency access to tenant admin", () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: "admin", roles: ["admin"] } });

    render(<RulesTab />);
    expect(screen.getByText("Нет доступа к правилам обучения")).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("keeps position rules read-only and links to the training tab", async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === "/v1/positions")
        return { data: [{ id: "position-1", name: "Manager", department: "Sales", course_ids: ["course-1"] }] } as any;
      if (url === "/v1/departments") return { data: { departments: [] } } as any;
      if (url.startsWith("/v1/courses")) return { data: [{ id: "course-1", title: "Safety" }] } as any;
      throw new Error(`Unexpected GET ${url}`);
    });

    render(<RulesTab />);
    fireEvent.click(await screen.findByRole("button", { name: /Manager/ }));

    expect(await screen.findByRole("link", { name: /Открыть карточку должности/ })).toHaveAttribute(
      "href",
      "/positions/position-1?tab=training",
    );
    expect(screen.queryByRole("button", { name: /Добавить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Убрать/ })).not.toBeInTheDocument();
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it("keeps department rules editable while position controls stay absent", async () => {
    apiMock.get.mockImplementation(async (url: string) => {
      if (url === "/v1/positions") return { data: [] } as any;
      if (url === "/v1/departments")
        return {
          data: {
            departments: [
              {
                id: "department-1",
                name: "Sales",
                slug: "sales",
                course_ids: ["course-0"],
              },
            ],
          },
        } as any;
      if (url.startsWith("/v1/courses"))
        return {
          data: [
            { id: "course-0", title: "Existing course" },
            { id: "course-1", title: "Safety" },
          ],
        } as any;
      throw new Error(`Unexpected GET ${url}`);
    });
    apiMock.post.mockResolvedValue({ data: { re_enrolled: 0 } } as any);

    render(<RulesTab />);
    fireEvent.click(await screen.findByRole("button", { name: /Sales/ }));
    expect(await screen.findByText("Existing course")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Убрать" })).toBeInTheDocument();
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: "course-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/v1/departments/department-1/courses", {
        course_id: "course-1",
        required: true,
      }),
    );
  });

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
