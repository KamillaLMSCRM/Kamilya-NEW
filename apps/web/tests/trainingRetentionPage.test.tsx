import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrainingRetentionPage from "@/features/training-retention/TrainingRetentionPage";
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
  apiMock.get.mockResolvedValue({ data: { items: [] } } as any);
});

describe("TrainingRetentionPage", () => {
  it("is read-only and exposes no policy or purge mutations", async () => {
    render(<TrainingRetentionPage />);

    expect(await screen.findByRole("note")).toHaveTextContent(/read-only|только для просмотра/i);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith("/v1/training-retention/policies");
    expect(apiMock.post).not.toHaveBeenCalled();
    expect(apiMock.patch).not.toHaveBeenCalled();
    expect(apiMock.delete).not.toHaveBeenCalled();
  });

  it("shows the effective retention period in days and years", async () => {
    apiMock.get.mockResolvedValue({ data: { items: [{ id: "policy-1", procedure_type: "training", retention_days: 1825, legal_basis: null, local_basis: "Internal retention schedule", active: true }] } } as any);

    render(<TrainingRetentionPage />);

    expect(await screen.findByText(/1825/)).toHaveTextContent(/5/);
    expect(screen.getByText(/Internal retention schedule/)).toBeInTheDocument();
  });

  it("keeps the retention screen unavailable to tenant admins", () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: "admin", roles: ["admin"] } });
    render(<TrainingRetentionPage />);

    expect(screen.getByText(/evidence retention is unavailable|Раздел хранения доказательств недоступен/i)).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});
