import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PositionQualificationCard } from "@/features/positions/PositionQualificationCard";
import { api } from "@/lib/api";

import { getQualificationCard, getQualificationHistory } from "@/features/positions/qualification-api";
import type { PositionQualificationCardData } from "@/features/positions/qualification-types";

let requestedTab = "profile";
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn() }),
  usePathname: () => "/positions/position-1",
  useSearchParams: () => new URLSearchParams(requestedTab ? `tab=${requestedTab}` : ""),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/features/positions/qualification-api", () => ({
  getQualificationCard: vi.fn(),
  getQualificationHistory: vi.fn(),
  replaceMandatoryTraining: vi.fn(),
  replacePositionCompetencies: vi.fn(),
  restoreQualificationVersion: vi.fn(),
  updateQualificationProfile: vi.fn(),
}));

const apiMock = vi.mocked(api);
const getCardMock = vi.mocked(getQualificationCard);
const getHistoryMock = vi.mocked(getQualificationHistory);

const card: PositionQualificationCardData = {
  profile: {
    id: "position-1",
    tenant_id: "tenant-1",
    name: "Оператор",
    department: "Производство",
    level: "Специалист",
    responsibilities: "Работа на линии",
    requirements: "Инструктаж",
    employee_count: 2,
    current_employee_count: 2,
    created_at: "2026-07-25T10:00:00Z",
  },
  instruction: null,
  competencies: [],
  training: {
    position_courses: [],
    department_courses: [],
    competency_courses: [],
    effective_courses: [],
  },
  onboarding_quiz: null,
  employees: { active_count: 2 },
  latest_version: null,
  history_count: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  requestedTab = "profile";
  getCardMock.mockResolvedValue(card);
  getHistoryMock.mockResolvedValue([]);
  apiMock.get.mockImplementation(async (url: string) => {
    if (url === "/v1/competencies") return { data: [] } as never;
    if (url.startsWith("/v1/courses")) return { data: [] } as never;
    throw new Error(`Unexpected GET ${url}`);
  });
});

describe("PositionQualificationCard", () => {
  it("renders the core card independently from optional catalogs", async () => {
    apiMock.get.mockRejectedValue(new Error("catalog unavailable"));

    render(<PositionQualificationCard positionId="position-1" />);

    expect(await screen.findByRole("heading", { name: "Оператор" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Работа на линии")).toBeInTheDocument();
    expect(screen.queryByText(/справочники компетенций или курсов временно недоступны/i)).not.toBeInTheDocument();
  });

  it("shows a recoverable catalog error on the training tab", async () => {
    requestedTab = "training";
    apiMock.get.mockRejectedValue(new Error("catalog unavailable"));

    render(<PositionQualificationCard positionId="position-1" />);

    expect(await screen.findByText(/справочники компетенций или курсов временно недоступны/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Повторить/i })).toBeInTheDocument();
    expect(screen.getByText(/Итоговый набор/i)).toBeInTheDocument();
  });

  it("shows a retry state when the qualification aggregate fails", async () => {
    getCardMock.mockRejectedValue(new Error("aggregate unavailable"));

    render(<PositionQualificationCard positionId="position-1" />);

    expect(await screen.findByText(/Не удалось загрузить карточку должности/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Повторить/i })).toBeInTheDocument();
    await waitFor(() => expect(getCardMock).toHaveBeenCalledWith("position-1"));
  });
});
