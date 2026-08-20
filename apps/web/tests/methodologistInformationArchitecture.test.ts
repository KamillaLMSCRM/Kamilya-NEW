import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { canAccessRegisteredRoute, getNavigationRoutes } from "@/lib/routeRegistry";

const staffSource = readFileSync(resolve(process.cwd(), "src/app/admin/staff/page.tsx"), "utf8");
const rulesSource = readFileSync(resolve(process.cwd(), "src/features/training-rules/TrainingRulesPage.tsx"), "utf8");
const topBarSource = readFileSync(resolve(process.cwd(), "src/components/layout/TopBar.tsx"), "utf8");
const languageSwitcherSource = readFileSync(resolve(process.cwd(), "src/components/LanguageSwitcher.tsx"), "utf8");
const qualificationCardSource = readFileSync(
  resolve(process.cwd(), "src/features/positions/PositionQualificationCard.tsx"),
  "utf8",
);

describe("methodologist information architecture", () => {
  it("registers rules for the active methodologist only", () => {
    expect(canAccessRegisteredRoute("methodologist", "/training-rules")).toBe(true);
    expect(canAccessRegisteredRoute("admin", "/training-rules")).toBe(false);
    expect(getNavigationRoutes("methodologist", "sidebar").some((route) => route.id === "training-rules")).toBe(false);
    expect(getNavigationRoutes("admin", "sidebar").some((route) => route.id === "training-rules")).toBe(false);
    expect(staffSource).toContain('href={`/training-rules?scope=department&department_id=${dept.id}`}');
  });

  it("keeps staff tabs URL-backed and preserves legacy rule links", () => {
    expect(staffSource).toContain('type Tab = "import" | "structure"');
    expect(staffSource).toContain('router.replace("/training-rules?scope=department")');
    expect(staffSource).toContain('router.replace("/training-rules?scope=organization")');
    expect(staffSource).toContain('router.replace(`/staff?${params.toString()}`)');
    expect(staffSource).not.toContain("RulesTab");
    expect(staffSource).not.toContain("CompanyCoursesTab");
  });

  it("keeps multi-sheet import reviewable and opens the resulting structure", () => {
    expect(staffSource).toContain("const [sheets, setSheets]");
    expect(staffSource).toContain('sheet.sheet_kind === "reference"');
    expect(staffSource).toContain('sheet.sheet_kind === "needs_mapping"');
    expect(staffSource).toContain("setMappingDirty(true)");
    expect(staffSource).toContain("setStructureRefreshKey((value) => value + 1)");
    expect(staffSource).toContain('selectTab("structure")');
    expect(staffSource).toContain("overflow-x-auto overflow-y-auto");
    expect(staffSource).toContain("Для имени сотрудника укажите либо отдельные колонки");
    expect(staffSource).toContain('field.key === "first_name" || field.key === "last_name"');
  });

  it("accepts legacy Excel staffing files and explains branch section rows", () => {
    expect(staffSource).toContain('accept=".xls,.xlsx,.csv"');
    expect(staffSource).toContain("Старые штатные");
    expect(staffSource).toContain("с адресами филиалов");
    expect(staffSource).toContain("Сотрудник /");
    expect(staffSource).toContain("ФИО / full_name");
  });

  it("uses canonical department and position ids for manual employees", () => {
    expect(staffSource).toContain('api.get<{ departments: DepartmentOption[] }>("/v1/departments")');
    expect(staffSource).toContain('api.get<PositionOption[]>("/v1/positions")');
    expect(staffSource).toContain("department_id: manualForm.department_id || undefined");
    expect(staffSource).toContain("position_id: manualForm.position_id || undefined");
    expect(staffSource).toContain("position.department_id === manualForm.department_id");
  });

  it("keeps large structures searchable and separately collapsible by position", () => {
    expect(staffSource).toContain("const [expandedPositions");
    expect(staffSource).toContain("const [query, setQuery]");
    expect(staffSource).toContain("filteredDepartments");
    expect(staffSource).toContain("togglePosition(pos.id)");
  });

  it("keeps the shared top bar within a phone viewport", () => {
    expect(topBarSource).toContain("px-3 sm:px-6");
    expect(topBarSource).toContain("w-28 rounded-lg");
    expect(topBarSource).toContain("hidden h-9 w-9");
    expect(languageSwitcherSource).toContain("sm:gap-2 sm:px-2.5");
    expect(languageSwitcherSource).toContain("hidden h-4 w-4");
  });

  it("keeps structure free of training progress metrics and requires preview before rules mutations", () => {
    expect(staffSource).not.toMatch(/ready_percent|overall_ready_percent|assigned_courses|completed_courses/);
    expect(staffSource).toContain('href="/training-log"');
    expect(rulesSource).toContain('api.post<RulePreview>("/v1/training-rules/preview"');
    expect(rulesSource).toContain('api.post("/v1/training-rules/organization"');
    expect(rulesSource).toContain('api.post(`/v1/departments/${pending.departmentId}/courses`');
    expect(rulesSource).toContain('api.delete(`/v1/departments/${pending.departmentId}/courses/${pending.courseId}`');
    expect(rulesSource).toContain('pending.operation === "detach" ? "danger" : "warning"');
    expect(rulesSource).toContain('className="min-w-0 overflow-hidden"');
    expect(rulesSource).toContain('grid-cols-[minmax(0,1fr)]');
  });

  it("opens qualification cards from staff structure without a duplicate positions menu", () => {
    const sidebar = getNavigationRoutes("methodologist", "sidebar").map((route) => route.id);
    const commands = getNavigationRoutes("methodologist", "commandPalette").map((route) => route.id);

    expect(sidebar).toContain("staff");
    expect(sidebar).not.toContain("positions");
    expect(commands).not.toContain("positions");
    expect(staffSource).toContain('href={`/positions/${pos.id}?tab=training`}');
    expect(staffSource).toContain('href={`/assignments?user_id=${emp.id}`}');
  });

  it("makes course assignment and no-email access discoverable to a methodologist", () => {
    const sidebar = getNavigationRoutes("methodologist", "sidebar");
    const assignments = sidebar.find((route) => route.id === "course-assignments");

    expect(assignments).toBeDefined();
    expect(assignments?.labelKey).toBe("nav.assignmentsAndAccess");
    expect(getNavigationRoutes("admin", "sidebar").some((route) => route.id === "course-assignments")).toBe(false);
  });

  it("does not advertise the unfinished position onboarding quiz as a usable flow", () => {
    expect(qualificationCardSource).not.toContain('{ id: "onboarding", label: "Onboarding-тест"');
    expect(qualificationCardSource).not.toContain("AI-рекомендациях и onboarding-тесте");
  });

  it("uses an accessible employee modal and a shared Kazakhstan phone mask", () => {
    expect(staffSource).toContain('aria-labelledby="manual-employee-title"');
    expect(staffSource).toContain('className="inline-flex h-11 w-11');
    expect(staffSource).toContain("items-start justify-center overflow-y-auto");
    expect(staffSource).toContain("onClick={closeManualModal}");
    expect(staffSource).toContain('formatKzPhone(e.target.value)');
    expect(staffSource).toContain('maxLength={18}');
    expect(staffSource).toContain('isCompleteKzPhone(manualForm.phone)');
  });
});
