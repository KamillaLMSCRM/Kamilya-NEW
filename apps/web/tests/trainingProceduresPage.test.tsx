import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrainingProceduresPage from "@/features/training-procedures/TrainingProceduresPage";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
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

beforeEach(() => {
  vi.clearAllMocks();
  setRole("methodologist");
  apiMock.get.mockResolvedValue({ data: { items: [] } } as any);
});

describe("TrainingProceduresPage", () => {
  it("states that this catalog does not infer attestation or admission from ordinary training", async () => {
    render(<TrainingProceduresPage />);

    expect(await screen.findByRole("note")).toHaveTextContent(
      /фактическая аттестация.*отдельное решение о допуске/i,
    );
    expect(apiMock.get).toHaveBeenCalledWith("/v1/training-procedures");
  });

  it("states that configured EDS and commission rules are not completed evidence", async () => {
    render(<TrainingProceduresPage />);

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/OTP.*не является ЭЦП/i);
    expect(note).toHaveTextContent(/Результат теста.*не является решением о допуске/i);
  });

  it("does not call the catalog API for a tenant admin", () => {
    setRole("admin");

    render(<TrainingProceduresPage />);

    expect(screen.getByText(/Процедуры подтверждения недоступны/i)).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });

  it("keeps the configurable type choices separate from knowledge checks", async () => {
    render(<TrainingProceduresPage />);

    await waitFor(() => expect(screen.getByLabelText(/Тип процедуры/i)).toBeInTheDocument());
    const typeSelect = screen.getByLabelText(/Тип процедуры/i) as HTMLSelectElement;
    expect(Array.from(typeSelect.options).map((option) => option.value)).toEqual([
      "acknowledgement",
      "internal_attestation",
      "admission_decision",
    ]);
    expect(typeSelect.options.namedItem("knowledge_check")).toBeNull();
  });
});
