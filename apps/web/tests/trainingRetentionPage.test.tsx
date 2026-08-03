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
  it("defaults to dry-run and explains irreversible deletion and legal holds", async () => {
    render(<TrainingRetentionPage />);

    expect(await screen.findByRole("note")).toHaveTextContent(/irreversible|необратимо/i);
    expect(screen.getByText(/legal hold/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /preview purge|предпросмотр очистки/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute purge/i })).not.toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith("/v1/training-retention/policies");
  });

  it("keeps the retention screen unavailable to tenant admins", () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, role: "admin", roles: ["admin"] } });
    render(<TrainingRetentionPage />);

    expect(screen.getByText(/evidence retention is unavailable|Раздел хранения доказательств недоступен/i)).toBeInTheDocument();
    expect(apiMock.get).not.toHaveBeenCalled();
  });
});
