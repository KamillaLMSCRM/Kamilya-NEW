import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrainingRulesPage from "@/features/training-rules/TrainingRulesPage";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

const apiMock = vi.mocked(api);

function setRole(role: "admin" | "methodologist") {
  useAuthStore.setState({
    accessToken: "test-token",
    initialized: true,
    user: {
      user_id: `${role}-1`,
      tenant_id: "tenant-1",
      tenant: { id: "tenant-1", name: "Test tenant" },
      telegram_id: "",
      role,
      roles: [role],
      full_name: role,
      email: `${role}@example.com`,
    },
  });
}

function mockRuleReads() {
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === "/v1/courses?per_page=100") {
      return {
        data: [
          { id: "course-existing", title: "Existing course", status: "archived" },
          { id: "course-new", title: "Safety", status: "published" },
        ],
      } as any;
    }
    if (url === "/v1/training-rules/organization") {
      return { data: { rules: [{ course_id: "course-existing" }] } } as any;
    }
    if (url === "/v1/departments") {
      return {
        data: {
          departments: [{ id: "department-1", name: "Sales", slug: "sales", course_ids: [] }],
        },
      } as any;
    }
    if (url === "/v1/positions") {
      return {
        data: [{ id: "position-1", name: "Manager", department: "Sales", course_ids: ["course-existing"] }],
      } as any;
    }
    throw new Error(`Unexpected GET ${url}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  setRole("methodologist");
});

describe("TrainingRulesPage", () => {
  it("denies tenant admin locally without API calls", () => {
    setRole("admin");

    render(<TrainingRulesPage />);

    expect(screen.getByText("Доступ к правилам обучения закрыт")).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("keeps archived attached rules readable and position rules read-only", async () => {
    mockRuleReads();

    render(<TrainingRulesPage />);

    expect(await screen.findByText("Existing course")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Должность" }));
    expect(await screen.findByRole("link", { name: /Открыть карточку/ })).toHaveAttribute(
      "href",
      "/positions/position-1?tab=training",
    );
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it("requires a consequence preview before attaching an organization rule", async () => {
    mockRuleReads();
    apiMock.post.mockResolvedValue({
      data: {
        affected_employees: 3,
        enrollments_to_add: 2,
        in_progress_to_remove: 0,
        protected_completed: 1,
        protected_other_sources: 0,
      },
    } as any);

    render(<TrainingRulesPage />);

    const select = await screen.findByLabelText("Добавить курс");
    fireEvent.change(select, { target: { value: "course-new" } });
    fireEvent.click(screen.getByRole("button", { name: "Добавить" }));

    await waitFor(() =>
      expect(apiMock.post).toHaveBeenCalledWith("/v1/training-rules/preview", {
        scope: "organization",
        operation: "attach",
        course_id: "course-new",
      }),
    );
    expect(apiMock.post).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Предпросмотр изменения")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
