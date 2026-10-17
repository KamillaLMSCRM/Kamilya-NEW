import { api } from '@/lib/api';

export type StaffWorkspaceAccess = 'all' | 'active' | 'inactive';
export type StaffWorkspaceScope = 'direct' | 'subtree';

export interface StaffWorkspaceUnit {
  id: string;
  name: string;
  parent_id: string | null;
  unit_type: string | null;
  is_active: boolean;
  is_head_office: boolean;
  head_user_id: string | null;
  breadcrumb: string[];
  direct_count: number;
  subtree_count: number;
  hr_managed: boolean;
}

export interface StaffWorkspacePosition {
  id: string;
  name: string;
  department_id: string | null;
  is_active: boolean;
  employee_count: number;
  unit_counts: Record<string, number>;
}

export interface StaffWorkspaceOverview {
  units: StaffWorkspaceUnit[];
  positions: StaffWorkspacePosition[];
  total: number;
  unplaced_count: number;
}

export interface StaffWorkspaceEmployee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
  organization_unit_id: string | null;
  effective_unit_id: string | null;
  placement_source: string;
  position_id: string | null;
  position_name: string | null;
  hr_managed: boolean;
}

export interface StaffEmployeeRoster {
  items: StaffWorkspaceEmployee[];
  total: number;
  page: number;
  page_size: number;
}

export interface StaffEmployeeRosterQuery {
  unitId?: string;
  unplaced?: boolean;
  scope: StaffWorkspaceScope;
  access: StaffWorkspaceAccess;
  q?: string;
  positionId?: string;
  missingPosition?: boolean;
  page: number;
  pageSize?: number;
}

export interface StaffChangeCommand {
  kind: 'employee' | 'unit';
  target_id: string;
  organization_unit_id: string | null;
  position_id?: string;
  reason: string;
}

export interface StaffChangeTrainingImpact {
  added: number;
  no_longer_required: number;
  preserved_completed: number;
  preserved_other_sources: number;
  courses: StaffChangeCourseImpact[];
}

export interface StaffChangeCourseImpact {
  course_id: string;
  title: string;
  added: number;
  retained_previous: number;
}

export interface StaffChangeReportingImpact {
  user_id: string;
  full_name: string;
  before_count: number;
  after_count: number;
  gained: number;
  lost: number;
}

export interface StaffChangePreview {
  id: string;
  expires_at: string;
  kind: 'employee' | 'unit';
  target_id: string;
  from_path: string[];
  to_path: string[];
  affected_employees: number;
  training: StaffChangeTrainingImpact;
  reporting: StaffChangeReportingImpact[];
  warnings: string[];
}

export interface StaffChangeReceipt {
  plan_id: string;
  status: 'succeeded';
  affected_employees: number;
  added: number;
  preserved: number;
  executed_at: string;
}

export async function fetchStaffWorkspace(
  access: StaffWorkspaceAccess,
  signal?: AbortSignal,
): Promise<StaffWorkspaceOverview> {
  const response = await api.get<StaffWorkspaceOverview>('/v1/organization-units/workspace', {
    params: { access },
    signal,
  });
  return response.data;
}

export async function fetchStaffEmployees(
  query: StaffEmployeeRosterQuery,
  signal?: AbortSignal,
): Promise<StaffEmployeeRoster> {
  const response = await api.get<StaffEmployeeRoster>('/v1/organization-units/employees', {
    params: {
      unit_id: query.unitId,
      unplaced: query.unplaced || undefined,
      scope: query.scope,
      access: query.access,
      q: query.q?.trim() || undefined,
      position_id: query.positionId,
      missing_position: query.missingPosition || undefined,
      page: query.page,
      page_size: query.pageSize ?? 20,
    },
    signal,
  });
  return response.data;
}

export async function previewStaffChange(
  command: StaffChangeCommand,
  signal?: AbortSignal,
): Promise<StaffChangePreview> {
  const response = await api.post<StaffChangePreview>(
    '/v1/organization-units/changes/preview',
    command,
    { signal },
  );
  return response.data;
}

export async function confirmStaffChange(planId: string): Promise<StaffChangeReceipt> {
  const response = await api.post<StaffChangeReceipt>(
    `/v1/organization-units/changes/${encodeURIComponent(planId)}/confirm`,
    { confirmed: true },
  );
  return response.data;
}
