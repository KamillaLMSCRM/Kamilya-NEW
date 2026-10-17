'use client';

import Link from 'next/link';
import {
  AlertTriangle,
  BookOpenCheck,
  Building2,
  ChevronLeft,
  ChevronRight,
  MoveRight,
  Plus,
  RefreshCw,
  Users,
} from 'lucide-react';
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { Button, Card, CardContent, CardHeader, CardTitle, Modal } from '@/components/ui';
import { apiErrorMessage } from '@/lib/apiErrorMessage';
import { useAuthStore } from '@/store/authStore';

import {
  confirmStaffChange,
  fetchStaffEmployees,
  fetchStaffWorkspace,
  previewStaffChange,
  type StaffChangeCommand,
  type StaffChangePreview,
  type StaffChangeReceipt,
  type StaffEmployeeRoster,
  type StaffWorkspaceAccess,
  type StaffWorkspaceEmployee,
  type StaffWorkspaceOverview,
  type StaffWorkspacePosition,
  type StaffWorkspaceScope,
  type StaffWorkspaceUnit,
} from './StaffWorkspaceClient';
import {
  getOrganizationUnitTypeLabel,
  type OrganizationUnitNode,
} from './organizationStructure';

type WorkspaceView = 'schema' | 'people';
type DetailView = 'people' | 'positions' | 'training';

interface WorkspaceLocation {
  view: WorkspaceView;
  unit: 'all' | 'unplaced' | string;
  scope: StaffWorkspaceScope;
  access: StaffWorkspaceAccess;
  page: number;
}

interface EditableEmployee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
  position_id: string | null;
}

export interface StaffWorkspaceProps {
  onAddEmployee: (unitId: string | null) => void;
  onEditEmployee: (employee: EditableEmployee) => void;
  onEditUnit: (unit: OrganizationUnitNode) => void;
  onAddUnit: (parentId: string | null) => void;
  refreshKey: number;
}

interface ChangeDraft {
  kind: 'employee' | 'unit';
  target: StaffWorkspaceEmployee | StaffWorkspaceUnit;
  organizationUnitId: string;
  positionId: string;
  reason: string;
}

interface PendingConfirmation {
  storageKey: string;
  planId: string;
}

const PAGE_SIZE = 20;
const CHILD_BATCH_SIZE = 6;
const PENDING_CONFIRMATION_PREFIX = 'staff-structure:pending-confirmation';

const inputClassName = 'min-h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

const staffChangeErrorMessages: Record<string, string> = {
  staff_workspace_disabled: 'Рабочее пространство пока не включено в этой среде.',
  preview_stale: 'Данные изменились после предпросмотра. Получите новый предпросмотр.',
  preview_expired: 'Срок предпросмотра истёк. Получите новый предпросмотр.',
  hr_managed: 'Запись управляется HR-системой и не может быть изменена вручную.',
  serialization_conflict: 'Параллельное изменение не позволило выполнить перевод. Получите новый предпросмотр.',
  impact_snapshot_too_large: 'Изменение слишком велико для безопасного предпросмотра.',
  course_release_missing: 'Один из обязательных курсов не имеет опубликованной версии. Изменение не выполнено.',
  preview_limit: 'Достигнут лимит активных предпросмотров. Завершите текущие изменения или повторите позже.',
  inactive_target: 'Выбранное подразделение или сотрудник неактивны; ручное изменение недоступно.',
  inactive_position: 'Выбранная должность неактивна; ручное изменение недоступно.',
  hierarchy_cycle: 'Такое перемещение создаст цикл в структуре. Выберите другого родителя.',
  maximum_depth_exceeded: 'Перемещение превысит допустимую глубину структуры.',
  head_office_must_be_root: 'Головной офис должен оставаться корневым подразделением.',
  duplicate_sibling: 'На этом уровне уже есть подразделение с таким названием и типом.',
  student_only: 'Безопасный перевод доступен только для сотрудников с учебной ролью.',
  resource_not_found: 'Выбранная запись больше недоступна. Обновите рабочее пространство.',
  plan_not_found: 'Сохранённый план больше недоступен.',
};

function validView(value: string | null): WorkspaceView {
  return value === 'people' ? 'people' : 'schema';
}

function validScope(value: string | null): StaffWorkspaceScope {
  return value === 'direct' ? 'direct' : 'subtree';
}

function validAccess(value: string | null): StaffWorkspaceAccess {
  return value === 'all' || value === 'inactive' ? value : 'active';
}

function readLocation(): WorkspaceLocation {
  if (typeof window === 'undefined') {
    return { view: 'schema', unit: 'all', scope: 'subtree', access: 'active', page: 1 };
  }
  const params = new URLSearchParams(window.location.search);
  const unit = params.get('staff_unit') || 'all';
  const rawPage = Number(params.get('staff_page'));
  return normalizeLocation({
    view: validView(params.get('staff_view')),
    unit,
    scope: validScope(params.get('staff_scope')),
    access: validAccess(params.get('staff_access')),
    page: Number.isInteger(rawPage) && rawPage > 0 ? rawPage : 1,
  });
}

function normalizeLocation(location: WorkspaceLocation): WorkspaceLocation {
  if (location.unit === 'all') return { ...location, scope: 'subtree' };
  if (location.unit === 'unplaced') return { ...location, scope: 'direct' };
  return location;
}

function writeLocation(location: WorkspaceLocation, replace: boolean): void {
  const url = new URL(window.location.href);
  url.searchParams.set('tab', 'structure');
  url.searchParams.set('staff_view', location.view);
  url.searchParams.set('staff_unit', location.unit);
  url.searchParams.set('staff_scope', location.scope);
  url.searchParams.set('staff_access', location.access);
  url.searchParams.set('staff_page', String(location.page));
  window.history[replace ? 'replaceState' : 'pushState']({}, '', `${url.pathname}${url.search}${url.hash}`);
}

function formatPath(path: string[]): string {
  return path.filter(Boolean).join(' → ') || 'Без подразделения';
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU');
}

function accountLabel(active: boolean): string {
  return active ? 'Доступ активен' : 'Доступ закрыт';
}

function placementSourceLabel(source: string): string {
  if (source === 'explicit') return 'явно указанное подразделение';
  if (source === 'position_fallback') return 'подразделение должности';
  if (source === 'none') return 'подразделение не определено';
  return 'серверное правило размещения';
}

function employeeIdentity(employee: StaffWorkspaceEmployee): string {
  return employee.personnel_number
    ? `Табельный № ${employee.personnel_number}`
    : `ID ${employee.id.slice(0, 8)}`;
}

function humanizeError(error: unknown, fallback: string): string {
  const responseCode = responseErrorCode(error);
  if (responseCode) return staffChangeErrorMessages[responseCode];
  const message = apiErrorMessage(error, fallback);
  if (Object.hasOwn(staffChangeErrorMessages, message)) return staffChangeErrorMessages[message];
  if (message === fallback || /^HTTP \d{3}$/.test(message)) return message;
  return fallback;
}

function responseErrorCode(error: unknown): string | null {
  const data = (error as { response?: { data?: { detail?: unknown; message?: unknown } } } | null)?.response?.data;
  const candidates = [data?.detail, data?.message];
  const code = candidates.find((candidate): candidate is string => (
    typeof candidate === 'string' && Object.hasOwn(staffChangeErrorMessages, candidate)
  ));
  return code || null;
}

function hasHttpResponse(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  // An intermediary can return502/504 after the application already committed.
  // Only a definite client/business rejection establishes a failed mutation.
  return typeof status === 'number' && status >= 400 && status < 500;
}

function pendingConfirmationKey(tenantId: string, actorId: string): string {
  return `${PENDING_CONFIRMATION_PREFIX}:${encodeURIComponent(tenantId)}:${encodeURIComponent(actorId)}`;
}

function persistPendingConfirmation(storageKey: string, planId: string): void {
  window.sessionStorage.setItem(storageKey, planId);
  if (window.sessionStorage.getItem(storageKey) !== planId) {
    throw new Error('pending_confirmation_not_persisted');
  }
}

function clearPendingConfirmation(storageKey: string, planId: string): void {
  if (window.sessionStorage.getItem(storageKey) !== planId) return;
  window.sessionStorage.removeItem(storageKey);
}

function unitPath(unitId: string | null, unitsById: Map<string, StaffWorkspaceUnit>): StaffWorkspaceUnit[] {
  const result: StaffWorkspaceUnit[] = [];
  const visited = new Set<string>();
  let current = unitId ? unitsById.get(unitId) : undefined;
  while (current && !visited.has(current.id)) {
    result.unshift(current);
    visited.add(current.id);
    current = current.parent_id ? unitsById.get(current.parent_id) : undefined;
  }
  return result;
}

function unitLabel(unit: StaffWorkspaceUnit): string {
  return formatPath(unit.breadcrumb.length ? unit.breadcrumb : [unit.name]);
}

function positionLabel(position: StaffWorkspacePosition, unitsById: Map<string, StaffWorkspaceUnit>): string {
  const activity = position.is_active ? '' : ' · неактивна';
  if (!position.department_id) return `${position.name} · без подразделения${activity}`;
  const unit = unitsById.get(position.department_id);
  return unit ? `${position.name} · ${unitLabel(unit)}${activity}` : `${position.name} · подразделение недоступно${activity}`;
}

function toOrganizationUnitNode(
  unit: StaffWorkspaceUnit,
  units: StaffWorkspaceUnit[],
  positions: StaffWorkspacePosition[],
  ancestors = new Set<string>(),
): OrganizationUnitNode {
  const nextAncestors = new Set(ancestors);
  nextAncestors.add(unit.id);
  return {
    id: unit.id,
    name: unit.name,
    unit_type: unit.unit_type,
    parent_id: unit.parent_id,
    is_active: unit.is_active,
    is_head_office: unit.is_head_office,
    head_user_id: unit.head_user_id,
    department_count: units.filter((candidate) => candidate.parent_id === unit.id).length,
    position_count: positions.filter((position) => position.department_id === unit.id).length,
    employee_count: unit.direct_count,
    positions: positions
      .filter((position) => position.department_id === unit.id)
      .map((position) => ({
        id: position.id,
        name: position.name,
        department_id: position.department_id,
        employee_count: 0,
        employees: [],
      })),
    children: units
      .filter((candidate) => candidate.parent_id === unit.id && !nextAncestors.has(candidate.id))
      .map((child) => toOrganizationUnitNode(child, units, positions, nextAncestors)),
  };
}

function TabButton({
  selected,
  tabKey,
  controls,
  onClick,
  onKeyDown,
  children,
}: {
  selected: boolean;
  tabKey: string;
  controls: string;
  onClick: () => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      data-workspace-tab={tabKey}
      aria-selected={selected}
      aria-controls={controls}
      tabIndex={selected ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={`min-h-11 border-b-2 px-4 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
    >
      {children}
    </button>
  );
}
function useNarrowLayout(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener?.('change', update);
    return () => media.removeEventListener?.('change', update);
  }, []);
  return narrow;
}

export function StaffWorkspace({
  onAddEmployee,
  onEditEmployee,
  onEditUnit,
  onAddUnit,
  refreshKey,
}: StaffWorkspaceProps) {
  const authUser = useAuthStore((state) => state.user);
  const confirmationStorageKey = authUser?.tenant_id && authUser.user_id
    ? pendingConfirmationKey(authUser.tenant_id, authUser.user_id)
    : null;
  const [location, setLocation] = useState<WorkspaceLocation>(readLocation);
  const [overviewResponse, setOverviewResponse] = useState<StaffWorkspaceOverview | null>(null);
  const [overviewAccess, setOverviewAccess] = useState<StaffWorkspaceAccess | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [roster, setRoster] = useState<StaffEmployeeRoster | null>(null);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const [shownChildren, setShownChildren] = useState(CHILD_BATCH_SIZE);
  const [detailView, setDetailView] = useState<DetailView>('people');
  const [queryDraft, setQueryDraft] = useState('');
  const [query, setQuery] = useState('');
  const [positionFilter, setPositionFilter] = useState('all');
  const [changeDraft, setChangeDraft] = useState<ChangeDraft | null>(null);
  const [preview, setPreview] = useState<StaffChangePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmOutcomeUnknown, setConfirmOutcomeUnknown] = useState(false);
  const [receipt, setReceipt] = useState<StaffChangeReceipt | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [recoveryLoading, setRecoveryLoading] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [recoveryReceipt, setRecoveryReceipt] = useState<StaffChangeReceipt | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const overviewRequest = useRef(0);
  const rosterRequest = useRef(0);
  const previewController = useRef<AbortController | null>(null);
  const dialogSession = useRef(0);
  const confirmAttempt = useRef(0);
  const recoveryAttempt = useRef(0);
  const confirmationStorageKeyRef = useRef(confirmationStorageKey);
  const previousConfirmationStorageKey = useRef(confirmationStorageKey);
  const focusHeading = useRef<HTMLHeadingElement>(null);
  const narrowLayout = useNarrowLayout();
  const pendingConfirmationId = pendingConfirmation?.storageKey === confirmationStorageKey
    ? pendingConfirmation.planId
    : null;

  const navigate = useCallback((patch: Partial<WorkspaceLocation>, replace = false) => {
    setLocation((current) => {
      const next = normalizeLocation({ ...current, ...patch });
      writeLocation(next, replace);
      return next;
    });
  }, []);

  useEffect(() => {
    writeLocation(location, true);
    const onPopState = () => setLocation(readLocation());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
    // The initial URL is normalized once; later writes are performed by navigate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++overviewRequest.current;
    setOverviewLoading(true);
    setOverviewError(null);
    fetchStaffWorkspace(location.access, controller.signal)
      .then((data) => {
        if (requestId !== overviewRequest.current) return;
        setOverviewResponse(data);
        setOverviewAccess(location.access);
        setOverviewLoading(false);
      })
      .catch((error) => {
        if (controller.signal.aborted || requestId !== overviewRequest.current) return;
        setOverviewResponse(null);
        setOverviewAccess(null);
        setOverviewLoading(false);
        setOverviewError(humanizeError(error, 'Не удалось загрузить структуру.'));
      });
    return () => controller.abort();
  }, [location.access, refreshKey, reloadNonce]);

  const overview = overviewResponse && overviewAccess === location.access ? overviewResponse : null;

  const unitsById = useMemo(
    () => new Map((overview?.units || []).map((unit) => [unit.id, unit])),
    [overview],
  );
  const selectedUnit = location.unit === 'all' || location.unit === 'unplaced'
    ? null
    : unitsById.get(location.unit) || null;
  const selectionValid = location.unit === 'all' || location.unit === 'unplaced' || unitsById.has(location.unit);

  useEffect(() => {
    if (!overview || location.unit === 'all' || location.unit === 'unplaced' || unitsById.has(location.unit)) return;
    navigate({ unit: 'all', scope: 'subtree', page: 1 }, true);
  }, [location.unit, navigate, overview, unitsById]);

  useEffect(() => {
    if (!overview || !selectionValid) return;
    const controller = new AbortController();
    const requestId = ++rosterRequest.current;
    setRosterLoading(true);
    setRosterError(null);
    const showRosterFilters = location.view === 'people';
    fetchStaffEmployees({
      unitId: selectedUnit?.id,
      unplaced: location.unit === 'unplaced',
      scope: location.scope,
      access: location.access,
      q: showRosterFilters ? query : undefined,
      positionId: showRosterFilters && positionFilter !== 'all' && positionFilter !== 'missing' ? positionFilter : undefined,
      missingPosition: showRosterFilters && positionFilter === 'missing',
      page: location.page,
      pageSize: PAGE_SIZE,
    }, controller.signal)
      .then((data) => {
        if (requestId !== rosterRequest.current) return;
        setRoster(data);
        setRosterLoading(false);
        if (data.page !== location.page) navigate({ page: data.page }, true);
      })
      .catch((error) => {
        if (controller.signal.aborted || requestId !== rosterRequest.current) return;
        setRoster(null);
        setRosterLoading(false);
        setRosterError(humanizeError(error, 'Не удалось загрузить сотрудников.'));
      });
    return () => controller.abort();
  }, [location.access, location.page, location.scope, location.unit, location.view, navigate, overview, positionFilter, query, refreshKey, reloadNonce, selectedUnit?.id, selectionValid]);

  useEffect(() => {
    setShownChildren(CHILD_BATCH_SIZE);
    setDetailView('people');
    setQuery('');
    setQueryDraft('');
    setPositionFilter('all');
  }, [location.unit]);

  useEffect(() => {
    if (!preview) return;
    setClock(Date.now());
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [preview]);

  useEffect(() => () => previewController.current?.abort(), []);

  confirmationStorageKeyRef.current = confirmationStorageKey;

  useEffect(() => {
    const accountChanged = previousConfirmationStorageKey.current !== confirmationStorageKey;
    previousConfirmationStorageKey.current = confirmationStorageKey;
    recoveryAttempt.current += 1;
    setRecoveryLoading(false);
    setRecoveryError(null);
    setRecoveryReceipt(null);

    if (accountChanged) {
      dialogSession.current += 1;
      confirmAttempt.current += 1;
      previewController.current?.abort();
      setChangeDraft(null);
      setPreview(null);
      setPreviewError(null);
      setConfirmError(null);
      setConfirmOutcomeUnknown(false);
      setReceipt(null);
      setPreviewLoading(false);
      setConfirmLoading(false);
    }

    if (!confirmationStorageKey) {
      setPendingConfirmation(null);
      return;
    }
    try {
      const planId = window.sessionStorage.getItem(confirmationStorageKey);
      setPendingConfirmation(planId ? { storageKey: confirmationStorageKey, planId } : null);
    } catch {
      setPendingConfirmation(null);
      setRecoveryError('Не удалось проверить сохранённое подтверждение в этой вкладке. Повторите после восстановления доступа к хранилищу браузера.');
    }
  }, [confirmationStorageKey]);

  const selectedPath = selectedUnit ? unitPath(selectedUnit.id, unitsById) : [];
  const children = useMemo(() => {
    if (!overview || location.unit === 'unplaced') return [];
    const parentId = selectedUnit?.id ?? null;
    return overview.units.filter((unit) => unit.parent_id === parentId);
  }, [location.unit, overview, selectedUnit?.id]);
  const visibleChildren = children.slice(0, shownChildren);
  const selectedPopulationKeys = useMemo(() => {
    if (!overview) return new Set<string>();
    if (location.unit === 'unplaced') return new Set(['unplaced']);
    if (!selectedUnit) return new Set<string>();
    if (location.scope === 'direct') return new Set([selectedUnit.id]);
    const keys = new Set<string>();
    const pending = [selectedUnit.id];
    while (pending.length) {
      const unitId = pending.pop();
      if (!unitId || keys.has(unitId)) continue;
      keys.add(unitId);
      overview.units.forEach((unit) => {
        if (unit.parent_id === unitId) pending.push(unit.id);
      });
    }
    return keys;
  }, [location.scope, location.unit, overview, selectedUnit]);
  const localPositions = useMemo(() => (overview?.positions || [])
    .map((position) => ({
      position,
      localCount: Object.entries(position.unit_counts).reduce(
        (total, [unitId, count]) => total + (selectedPopulationKeys.has(unitId) ? count : 0),
        0,
      ),
      sharedAcrossUnits: Object.values(position.unit_counts).filter((count) => count > 0).length > 1,
    }))
    .filter(({ localCount }) => localCount > 0), [overview, selectedPopulationKeys]);
  const expired = Boolean(preview && Date.parse(preview.expires_at) <= clock);
  const confirmationLocked = confirmLoading || confirmOutcomeUnknown;

  const selectUnit = (unit: WorkspaceLocation['unit']) => {
    navigate({
      unit,
      scope: unit === 'all' ? 'subtree' : unit === 'unplaced' ? 'direct' : location.scope,
      page: 1,
    });
    window.requestAnimationFrame(() => focusHeading.current?.focus());
  };

  const handleTabKey = (event: ReactKeyboardEvent<HTMLButtonElement>, tabs: string[], current: string, select: (value: string) => void, focusPrefix = '') => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = tabs.indexOf(current);
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? tabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    select(tabs[nextIndex]);
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>(`[role="tab"][data-workspace-tab="${focusPrefix}${tabs[nextIndex]}"]`)?.focus();
    });
  };

  const closeChange = () => {
    if (confirmationLocked) return;
    dialogSession.current += 1;
    previewController.current?.abort();
    setChangeDraft(null);
    setPreview(null);
    setPreviewError(null);
    setConfirmError(null);
    setConfirmOutcomeUnknown(false);
    setReceipt(null);
    setPreviewLoading(false);
    setConfirmLoading(false);
  };

  const openEmployeeChange = (employee: StaffWorkspaceEmployee) => {
    if (employee.hr_managed || confirmationLocked || pendingConfirmationId) return;
    dialogSession.current += 1;
    setChangeDraft({
      kind: 'employee',
      target: employee,
      organizationUnitId: employee.organization_unit_id || '',
      positionId: employee.position_id || '',
      reason: '',
    });
    setPreview(null);
    setReceipt(null);
    setPreviewError(null);
    setConfirmError(null);
    setConfirmOutcomeUnknown(false);
  };

  const openUnitChange = (unit: StaffWorkspaceUnit) => {
    if (unit.hr_managed || !unit.is_active || confirmationLocked || pendingConfirmationId) return;
    dialogSession.current += 1;
    setChangeDraft({
      kind: 'unit',
      target: unit,
      organizationUnitId: unit.parent_id || '',
      positionId: '',
      reason: '',
    });
    setPreview(null);
    setReceipt(null);
    setPreviewError(null);
    setConfirmError(null);
    setConfirmOutcomeUnknown(false);
  };

  const updateChangeDraft = (patch: Partial<Pick<ChangeDraft, 'organizationUnitId' | 'positionId' | 'reason'>>) => {
    if (confirmLoading || confirmOutcomeUnknown) return;
    previewController.current?.abort();
    setChangeDraft((current) => current ? { ...current, ...patch } : current);
    setPreview(null);
    setReceipt(null);
    setPreviewError(null);
    setConfirmError(null);
    setConfirmOutcomeUnknown(false);
    setPreviewLoading(false);
  };

  const requestPreview = async () => {
    if (!changeDraft) return;
    const command: StaffChangeCommand = {
      kind: changeDraft.kind,
      target_id: changeDraft.target.id,
      organization_unit_id: changeDraft.organizationUnitId || null,
      reason: changeDraft.reason.trim(),
      ...(changeDraft.kind === 'employee' ? { position_id: changeDraft.positionId } : {}),
    };
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewLoading(true);
    setPreviewError(null);
    setConfirmError(null);
    try {
      const result = await previewStaffChange(command, controller.signal);
      if (controller.signal.aborted) return;
      setPreview(result);
      setClock(Date.now());
    } catch (error) {
      if (controller.signal.aborted) return;
      setPreviewError(humanizeError(error, 'Не удалось получить безопасный предпросмотр.'));
      setPreview(null);
    } finally {
      if (!controller.signal.aborted) setPreviewLoading(false);
    }
  };

  const confirmPreview = async () => {
    if (!preview || (expired && !confirmOutcomeUnknown)) return;
    if (!confirmationStorageKey) {
      setConfirmError('Не удалось привязать подтверждение к текущей учётной записи. Обновите сеанс и повторите попытку.');
      return;
    }
    const sessionId = dialogSession.current;
    const attemptId = ++confirmAttempt.current;
    const planId = preview.id;
    const storageKey = confirmationStorageKey;
    try {
      persistPendingConfirmation(storageKey, planId);
    } catch {
      setConfirmError('Не удалось безопасно сохранить идентификатор плана в этой вкладке. Подтверждение не отправлено. Разрешите хранилище браузера и повторите попытку.');
      return;
    }
    setPendingConfirmation({ storageKey, planId });
    setConfirmLoading(true);
    setConfirmError(null);
    try {
      const result = await confirmStaffChange(planId);
      clearPendingConfirmation(storageKey, planId);
      if (sessionId !== dialogSession.current || attemptId !== confirmAttempt.current
        || storageKey !== confirmationStorageKeyRef.current) return;
      setPendingConfirmation(null);
      setReceipt(result);
      setPreview(null);
      setConfirmOutcomeUnknown(false);
      setReloadNonce((value) => value + 1);
    } catch (error) {
      const definiteRejection = hasHttpResponse(error);
      if (definiteRejection) clearPendingConfirmation(storageKey, planId);
      if (sessionId !== dialogSession.current || attemptId !== confirmAttempt.current
        || storageKey !== confirmationStorageKeyRef.current) return;
      if (!hasHttpResponse(error)) {
        setConfirmOutcomeUnknown(true);
        setConfirmError(`Сервер не подтвердил результат. Исход операции неизвестен; не создавайте новый план. Повторите подтверждение того же плана ${planId}.`);
      } else {
        const code = responseErrorCode(error);
        const mustRefresh = code === 'preview_stale' || code === 'preview_expired' || code === 'serialization_conflict';
        setPendingConfirmation(null);
        setConfirmOutcomeUnknown(false);
        setConfirmError(`${humanizeError(error, 'Не удалось подтвердить изменение.')} ${mustRefresh ? 'Получите новый предпросмотр.' : 'Изменение не выполнено.'}`);
        setPreview(null);
      }
    } finally {
      if (sessionId === dialogSession.current && attemptId === confirmAttempt.current) setConfirmLoading(false);
    }
  };

  const retryPendingConfirmation = async () => {
    if (!pendingConfirmationId || !confirmationStorageKey || recoveryLoading) return;
    const planId = pendingConfirmationId;
    const storageKey = confirmationStorageKey;
    const attemptId = ++recoveryAttempt.current;
    try {
      persistPendingConfirmation(storageKey, planId);
    } catch {
      setRecoveryError('Не удалось безопасно сохранить идентификатор плана в этой вкладке. Подтверждение не отправлено.');
      return;
    }
    setRecoveryLoading(true);
    setRecoveryError(null);
    try {
      const result = await confirmStaffChange(planId);
      clearPendingConfirmation(storageKey, planId);
      if (attemptId !== recoveryAttempt.current || storageKey !== confirmationStorageKeyRef.current) return;
      setPendingConfirmation(null);
      setRecoveryReceipt(result);
      setReloadNonce((value) => value + 1);
    } catch (error) {
      const definiteRejection = hasHttpResponse(error);
      if (definiteRejection) clearPendingConfirmation(storageKey, planId);
      if (attemptId !== recoveryAttempt.current || storageKey !== confirmationStorageKeyRef.current) return;
      if (definiteRejection) {
        setPendingConfirmation(null);
        setRecoveryError(`${humanizeError(error, 'Не удалось подтвердить сохранённый план.')} Изменение не выполнено.`);
      } else {
        setRecoveryError(`Сервер не подтвердил результат. Исход операции неизвестен; сохранён план ${planId}. Повторите подтверждение этого же плана.`);
      }
    } finally {
      if (attemptId === recoveryAttempt.current && storageKey === confirmationStorageKeyRef.current) {
        setRecoveryLoading(false);
      }
    }
  };

  const renderRoster = (compact = false) => {
    if (rosterLoading) {
      return <div className="p-5 text-sm text-muted-foreground" role="status">Загрузка сотрудников…</div>;
    }
    if (rosterError) {
      return (
        <div className="m-4 rounded-lg border border-destructive/30 bg-destructive/5 p-4" role="alert">
          <p className="font-medium">Список сотрудников недоступен</p>
          <p className="mt-1 text-sm text-muted-foreground">{rosterError}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => setReloadNonce((value) => value + 1)}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Повторить
          </Button>
        </div>
      );
    }
    if (!roster || roster.items.length === 0) {
      return (
        <div className="p-6 text-center text-sm text-muted-foreground">
          По выбранным условиям сотрудников нет.
          {!compact && (query || positionFilter !== 'all') && (
            <div><Button type="button" variant="link" onClick={() => { setQuery(''); setQueryDraft(''); setPositionFilter('all'); navigate({ page: 1 }); }}>Сбросить фильтры</Button></div>
          )}
        </div>
      );
    }
    const items = compact ? roster.items.slice(0, 4) : roster.items;
    return (
      <div className={compact ? 'divide-y divide-border' : 'divide-y divide-border px-4'}>
        {items.map((employee) => {
          const effectiveUnit = employee.effective_unit_id ? unitsById.get(employee.effective_unit_id) : undefined;
          return (
            <article
              key={employee.id}
              data-roster-layout={compact ? 'compact' : 'full'}
              className={compact
                ? 'grid min-w-0 gap-3 py-4'
                : 'grid min-w-0 gap-3 py-4 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] sm:items-start'}
            >
              <div className="min-w-0">
                <p className="break-words font-semibold text-foreground [overflow-wrap:anywhere]">{employee.full_name}</p>
                <p className="break-all text-xs text-muted-foreground">{employeeIdentity(employee)}</p>
                <span className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${employee.is_active ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground'}`}>
                  {accountLabel(employee.is_active)}
                </span>
                {employee.hr_managed && <p className="mt-2 text-xs font-medium text-amber-700">Управляется HR-системой: ручной перевод заблокирован.</p>}
              </div>
              <div className="min-w-0 break-words text-sm [overflow-wrap:anywhere]">
                <p>{employee.position_name || 'Должность не указана'}</p>
                <p className="mt-1 text-xs text-muted-foreground">{effectiveUnit ? unitLabel(effectiveUnit) : 'Без подразделения'}</p>
                <p className="mt-1 text-xs text-muted-foreground">Источник размещения: {placementSourceLabel(employee.placement_source)}</p>
              </div>
              <div className={`flex min-w-0 flex-wrap gap-2 ${compact ? '' : 'sm:justify-end'}`}>
                <Button type="button" variant="ghost" size="sm" onClick={() => onEditEmployee({
                  id: employee.id,
                  full_name: employee.full_name,
                  personnel_number: employee.personnel_number,
                  is_active: employee.is_active,
                  position_id: employee.position_id,
                })}>Изменить</Button>
                <Button type="button" variant="outline" size="sm" disabled={employee.hr_managed || Boolean(pendingConfirmationId)} onClick={() => openEmployeeChange(employee)}>
                  <MoveRight className="mr-1.5 h-4 w-4" aria-hidden="true" />Перевести
                </Button>
              </div>
            </article>
          );
        })}
      </div>
    );
  };

  const detailPanel = location.view === 'schema' && (selectedUnit || location.unit === 'unplaced') ? (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">Выбранное место</p>
        <CardTitle>{selectedUnit?.name || 'Без подразделения'}</CardTitle>
        <p className="text-xs text-muted-foreground">{selectedUnit ? unitLabel(selectedUnit) : 'Служебная выборка, а не подразделение'}</p>
        {selectedUnit?.hr_managed && (
          <p className="rounded-md bg-amber-50 p-3 text-xs text-amber-800">Это подразделение управляется HR-системой. Ручное перемещение заблокировано.</p>
        )}
      </CardHeader>
      <CardContent>
        <div role="tablist" aria-label="Содержимое подразделения" className="flex border-b border-border">
          {(['people', 'positions', 'training'] as DetailView[]).map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              data-workspace-tab={`detail-${tab}`}
              aria-selected={detailView === tab}
              aria-controls="staff-unit-detail"
              tabIndex={detailView === tab ? 0 : -1}
              onClick={() => setDetailView(tab)}
              onKeyDown={(event) => handleTabKey(event, ['people', 'positions', 'training'], detailView, (value) => setDetailView(value as DetailView), 'detail-')}
              className={`min-h-10 flex-1 border-b-2 px-2 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${detailView === tab ? 'border-primary text-primary' : 'border-transparent text-muted-foreground'}`}
            >
              {tab === 'people' ? 'Люди' : tab === 'positions' ? 'Должности' : 'Обучение'}
            </button>
          ))}
        </div>
        <div id="staff-unit-detail" role="tabpanel" className="pt-3">
          {detailView === 'people' && renderRoster(true)}
          {detailView === 'positions' && (
            <div className="divide-y divide-border">
              {localPositions.length ? localPositions.map(({ position, localCount, sharedAcrossUnits }) => (
                <div key={position.id} className="py-3">
                  <p className="font-medium">{position.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">В выбранном составе: {localCount}. Во всей компании при текущем фильтре доступа: {position.employee_count}.</p>
                  {sharedAcrossUnits && <p className="mt-1 text-xs font-medium text-amber-700">Общая должность используется в нескольких подразделениях. Изменение её учебных правил может затронуть не только выбранное место.</p>}
                </div>
              )) : <p className="py-4 text-sm text-muted-foreground">Для этого места должности не указаны.</p>}
            </div>
          )}
          {detailView === 'training' && (
            <div className="space-y-3 text-sm">
              <p>Правила обучения показывают обязательные курсы для компании, подразделения и должности. Откройте правила, чтобы изменить требования, или назначения, чтобы проверить обучение сотрудников.</p>
              <div className="flex flex-wrap gap-2">
                <Link href="/training-rules" className="inline-flex min-h-10 items-center rounded-md border border-input px-3 font-medium hover:bg-accent">
                  <BookOpenCheck className="mr-2 h-4 w-4" aria-hidden="true" />Правила обучения
                </Link>
                <Link href="/assignments" className="inline-flex min-h-10 items-center rounded-md border border-input px-3 font-medium hover:bg-accent">
                  <Users className="mr-2 h-4 w-4" aria-hidden="true" />Назначения
                </Link>
              </div>
            </div>
          )}
        </div>
        <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
          <Button type="button" size="sm" onClick={() => onAddEmployee(selectedUnit?.id || null)}><Plus className="mr-1.5 h-4 w-4" aria-hidden="true" />Сотрудник</Button>
          {selectedUnit && <Button type="button" variant="outline" size="sm" onClick={() => onAddUnit(selectedUnit.id)}>Подразделение</Button>}
          {selectedUnit && <Button type="button" variant="ghost" size="sm" onClick={() => onEditUnit(toOrganizationUnitNode(selectedUnit, overview?.units || [], overview?.positions || []))}>Изменить</Button>}
          {selectedUnit && <Button type="button" variant="outline" size="sm" disabled={selectedUnit.hr_managed || !selectedUnit.is_active || Boolean(pendingConfirmationId)} onClick={() => openUnitChange(selectedUnit)}>Переместить</Button>}
        </div>
        {selectedUnit?.hr_managed && <p className="mt-4 text-xs text-muted-foreground">Подразделение управляется кадровой системой. Ручное перемещение недоступно, чтобы не перезаписать кадровые данные.</p>}
      </CardContent>
    </Card>
  ) : null;

  if (!overview && (overviewLoading || overviewAccess !== location.access)) {
    return <div className="rounded-xl border border-border p-8 text-center text-sm text-muted-foreground" role="status">Загрузка структуры и сотрудников…</div>;
  }

  if (overviewError || !overview) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center" role="alert">
        <p className="font-semibold">Структура недоступна</p>
        <p className="mt-1 text-sm text-muted-foreground">{overviewError || 'Ответ сервера не получен.'}</p>
        <Button type="button" variant="outline" className="mt-4" onClick={() => setReloadNonce((value) => value + 1)}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Повторить</Button>
      </div>
    );
  }

  const rosterStart = roster?.total ? (roster.page - 1) * roster.page_size + 1 : 0;
  const rosterEnd = roster ? Math.min(roster.page * roster.page_size, roster.total) : 0;
  const totalPages = roster ? Math.max(1, Math.ceil(roster.total / roster.page_size)) : 1;
  const changeDestinationUnit = changeDraft?.organizationUnitId ? unitsById.get(changeDraft.organizationUnitId) : null;
  const changePosition = changeDraft?.kind === 'employee'
    ? overview.positions.find((position) => position.id === changeDraft.positionId)
    : null;
  const canPreview = Boolean(
    changeDraft
    && changeDraft.reason.trim().length >= 3
    && (!changeDraft.organizationUnitId || changeDestinationUnit?.is_active)
    && (changeDraft.kind === 'unit' || changePosition?.is_active),
  );

  return (
    <section aria-label="Рабочее пространство сотрудников" className="space-y-4">
      <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onAddUnit(selectedUnit?.id || null)}><Building2 className="mr-2 h-4 w-4" aria-hidden="true" />Добавить подразделение</Button>
          <Button type="button" onClick={() => onAddEmployee(selectedUnit?.id || null)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Добавить сотрудника</Button>
      </div>

      {pendingConfirmationId && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950" role="alert">
          <h3 className="font-semibold">Требуется проверить незавершённое подтверждение</h3>
          <p className="mt-1 text-sm">В этой вкладке сохранён план {pendingConfirmationId}. Новый перевод заблокирован, пока сервер не вернёт определённый результат.</p>
          {recoveryError && <p className="mt-2 text-sm">{recoveryError}</p>}
          <Button type="button" variant="outline" className="mt-3" disabled={recoveryLoading} onClick={retryPendingConfirmation}>
            {recoveryLoading ? 'Проверка подтверждения…' : 'Повторить подтверждение сохранённого плана'}
          </Button>
        </div>
      )}

      {!pendingConfirmationId && recoveryError && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
          {recoveryError}
        </div>
      )}

      {recoveryReceipt && (
        <div className="rounded-xl border border-success/30 bg-success/5 p-4" role="status">
          <h3 className="font-semibold text-success">Изменение выполнено</h3>
          <p className="mt-2 text-sm">Затронуто сотрудников: {recoveryReceipt.affected_employees}. Добавлено назначений: {recoveryReceipt.added}. Сохранено назначений: {recoveryReceipt.preserved}.</p>
          <p className="mt-1 text-xs text-muted-foreground">Выполнено {formatDateTime(recoveryReceipt.executed_at)} · план {recoveryReceipt.plan_id}</p>
        </div>
      )}

      <div role="tablist" aria-label="Представление структуры" className="flex border-b border-border">
        {(['schema', 'people'] as WorkspaceView[]).map((tab) => (
          <TabButton
            key={tab}
            tabKey={tab}
            selected={location.view === tab}
            controls="staff-workspace-panel"
            onClick={() => navigate({ view: tab, page: 1 })}
            onKeyDown={(event) => handleTabKey(event, ['schema', 'people'], location.view, (value) => navigate({ view: value as WorkspaceView, page: 1 }))}
          >
            {tab === 'schema' ? 'Схема' : 'Сотрудники'}
          </TabButton>
        ))}
      </div>

      <div className="grid gap-3 rounded-xl border border-border bg-muted/20 p-4 md:grid-cols-3">
        <label className="grid gap-1.5 text-sm font-medium">Подразделение
          <select className={inputClassName} value={location.unit} onChange={(event) => selectUnit(event.target.value)}>
            <option value="all">Вся компания</option>
            {overview.units.map((unit) => <option key={unit.id} value={unit.id}>{unitLabel(unit)}{unit.is_active ? '' : ' · неактивно'}</option>)}
            <option value="unplaced">Без подразделения · служебная выборка</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">Состав
          <select className={inputClassName} value={location.scope} disabled={location.unit === 'all' || location.unit === 'unplaced'} onChange={(event) => navigate({ scope: event.target.value as StaffWorkspaceScope, page: 1 })}>
            <option value="direct">Только непосредственно здесь</option>
            <option value="subtree">Вся выбранная ветка</option>
          </select>
        </label>
        <label className="grid gap-1.5 text-sm font-medium">Доступ к кабинету
          <select className={inputClassName} value={location.access} onChange={(event) => navigate({ access: event.target.value as StaffWorkspaceAccess, page: 1 })}>
            <option value="active">Активен</option>
            <option value="inactive">Закрыт</option>
            <option value="all">Любой</option>
          </select>
        </label>
      </div>

      <nav aria-label="Путь подразделения" className="flex flex-wrap items-center gap-2 text-sm">
        <button type="button" className="rounded text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => selectUnit('all')}>Компания</button>
        {selectedPath.map((unit) => (
          <span key={unit.id} className="contents">
            <span aria-hidden="true" className="text-muted-foreground">/</span>
            <button type="button" className="rounded text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => selectUnit(unit.id)}>{unit.name}</button>
          </span>
        ))}
        {location.unit === 'unplaced' && <><span aria-hidden="true">/</span><span>Без подразделения</span></>}
      </nav>

      <div id="staff-workspace-panel" role="tabpanel" className={`grid min-w-0 gap-4 ${detailPanel ? 'lg:grid-cols-[minmax(0,1fr)_22rem]' : ''}`}>
        {location.view === 'schema' ? (
          <Card className="min-w-0 overflow-hidden">
            <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
              <div>
                <CardTitle>Схема подразделений</CardTitle>
                <p className="mt-1 text-sm text-muted-foreground">Линия вложенности показывает место в структуре, а не личную подчинённость.</p>
              </div>
              {selectedUnit?.parent_id !== undefined && selectedUnit && (
                <Button type="button" variant="ghost" size="sm" onClick={() => selectUnit(selectedUnit.parent_id || 'all')}>↑ К родителю</Button>
              )}
            </CardHeader>
            <CardContent>
              <div className="mx-auto max-w-lg rounded-xl border-2 border-primary bg-primary/5 p-5 text-center">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{selectedUnit ? getOrganizationUnitTypeLabel(selectedUnit.unit_type) : location.unit === 'unplaced' ? 'Служебная выборка' : 'Компания'}</p>
                <h3 ref={focusHeading} tabIndex={-1} className="mt-1 text-xl font-semibold outline-none">{selectedUnit?.name || (location.unit === 'unplaced' ? 'Без подразделения' : 'Вся компания')}</h3>
                <div className="mt-3 flex flex-wrap justify-center gap-4 text-sm">
                  {selectedUnit && <span><strong className="block text-xl">{selectedUnit.direct_count}</strong>здесь</span>}
                  <span><strong data-testid="staff-overview-total" className="block text-xl">{selectedUnit?.subtree_count ?? (location.unit === 'unplaced' ? overview.unplaced_count : overview.total)}</strong>{selectedUnit ? 'во всей ветке' : 'сотрудников'}</span>
                  <span><strong className="block text-xl">{children.length}</strong>дочерних</span>
                </div>
              </div>
              {visibleChildren.length > 0 ? (
                <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {visibleChildren.map((unit) => (
                    <button key={unit.id} type="button" onClick={() => selectUnit(unit.id)} aria-label={`Открыть подразделение: ${unitLabel(unit)}`} className="flex min-h-36 flex-col items-start rounded-lg border border-border p-4 text-left hover:border-primary hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">{getOrganizationUnitTypeLabel(unit.unit_type)}{unit.is_head_office ? ' · Центральный офис' : ''}</span>
                      <strong className="mt-2">{unit.name}</strong>
                      <span className="mt-1 text-xs text-muted-foreground">{unit.direct_count} здесь · {unit.subtree_count} во всей ветке</span>
                      {unit.hr_managed && <span className="mt-2 text-xs font-medium text-amber-700">Управляется HR</span>}
                      <span className="mt-auto pt-3 text-sm font-medium text-primary">Открыть →</span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="mt-6 rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">{location.unit === 'unplaced' ? 'У служебной выборки нет дочерних подразделений.' : 'Дочерних подразделений нет.'}</div>
              )}
              {shownChildren < children.length && (
                <Button type="button" variant="outline" className="mx-auto mt-4 flex" onClick={() => setShownChildren((value) => value + CHILD_BATCH_SIZE)}>Показать ещё · осталось {children.length - shownChildren}</Button>
              )}
              {location.unit === 'all' && (
                <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
                  <div><strong>Без подразделения</strong><p className="text-xs text-muted-foreground">Служебная выборка; сотрудники остаются в общем списке.</p></div>
                  <Button type="button" variant="outline" onClick={() => selectUnit('unplaced')}>Открыть · {overview.unplaced_count}</Button>
                </div>
              )}
            </CardContent>
          </Card>
        ) : (
          <Card className="min-w-0 overflow-hidden">
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2"><CardTitle>Сотрудники</CardTitle><span className="rounded-full bg-muted px-2 py-0.5 text-xs">{roster?.total ?? 0} в выборке</span></div>
              <p className="text-sm text-muted-foreground">Фильтр «Доступ к кабинету» показывает, может ли сотрудник войти в систему. Это не кадровый статус и не признак трудоустройства.</p>
              <form className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); setQuery(queryDraft); navigate({ page: 1 }); }}>
                <label className="grid gap-1.5 text-sm">Поиск
                  <div className="flex gap-2"><input className={inputClassName} type="search" value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder="Имя или табельный номер" /><Button type="submit" variant="outline">Найти</Button></div>
                </label>
                <label className="grid gap-1.5 text-sm">Должность
                  <select className={inputClassName} value={positionFilter} onChange={(event) => { setPositionFilter(event.target.value); navigate({ page: 1 }); }}>
                    <option value="all">Все должности</option>
                    <option value="missing">Должность не указана</option>
                    {overview.positions.map((position) => <option key={position.id} value={position.id}>{positionLabel(position, unitsById)}</option>)}
                  </select>
                </label>
              </form>
            </CardHeader>
            <CardContent className="p-0">
              {renderRoster()}
              {roster && !rosterLoading && !rosterError && (
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-4">
                  <span className="text-sm text-muted-foreground">{rosterStart}–{rosterEnd} из {roster.total} · Страница {roster.page} из {totalPages}</span>
                  <div className="flex gap-2">
                    <Button type="button" variant="outline" disabled={roster.page <= 1} onClick={() => navigate({ page: roster.page - 1 })}><ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />Назад</Button>
                    <Button type="button" variant="outline" disabled={roster.page >= totalPages} onClick={() => navigate({ page: roster.page + 1 })}>Далее<ChevronRight className="ml-1 h-4 w-4" aria-hidden="true" /></Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {detailPanel && (narrowLayout ? (
          <details className="rounded-xl border border-border bg-background">
            <summary className="cursor-pointer px-4 py-3 font-medium text-primary">Люди, должности и обучение · {selectedUnit?.name || 'Без подразделения'}</summary>
            <div className="p-3 pt-0">{detailPanel}</div>
          </details>
        ) : <aside>{detailPanel}</aside>)}
      </div>

      <Modal
        open={Boolean(changeDraft)}
        onClose={closeChange}
        title={changeDraft?.kind === 'employee' ? 'Безопасный перевод сотрудника' : 'Безопасное перемещение подразделения'}
        className="max-w-2xl"
        dismissable={!confirmationLocked}
        closeOnBackdrop={!confirmationLocked}
      >
        {changeDraft && (
          <div className="space-y-4">
            <div className="rounded-lg bg-muted/50 p-3 text-sm">
              <strong>{changeDraft.kind === 'unit' ? (changeDraft.target as StaffWorkspaceUnit).name : (changeDraft.target as StaffWorkspaceEmployee).full_name}</strong>
              <p className="mt-1 text-xs text-muted-foreground">Проверьте последствия изменения, затем подтвердите его отдельным действием. До подтверждения данные не изменятся.</p>
            </div>
            {!receipt && (
              <>
                <label className="grid gap-1.5 text-sm font-medium">{changeDraft.kind === 'employee' ? 'Новое подразделение' : 'Новое родительское подразделение'}
                  <select className={inputClassName} value={changeDraft.organizationUnitId} disabled={confirmLoading || confirmOutcomeUnknown} onChange={(event) => updateChangeDraft({ organizationUnitId: event.target.value })}>
                    <option value="">{changeDraft.kind === 'employee' ? 'Без явного подразделения · применяется подразделение должности' : 'Корневое подразделение'}</option>
                    {overview.units
                      .filter((unit) => unit.id !== changeDraft.target.id)
                      .map((unit) => <option key={unit.id} value={unit.id} disabled={unit.hr_managed || !unit.is_active}>{unitLabel(unit)}{unit.hr_managed ? ' · управляется HR' : !unit.is_active ? ' · неактивно' : ''}</option>)}
                  </select>
                </label>
                {changeDraft.kind === 'employee' && (
                  <label className="grid gap-1.5 text-sm font-medium">Должность
                    <select className={inputClassName} value={changeDraft.positionId} disabled={confirmLoading || confirmOutcomeUnknown} onChange={(event) => updateChangeDraft({ positionId: event.target.value })} required>
                      <option value="">Выберите должность</option>
                      {overview.positions.map((position) => <option key={position.id} value={position.id} disabled={!position.is_active}>{positionLabel(position, unitsById)}</option>)}
                    </select>
                  </label>
                )}
                <label className="grid gap-1.5 text-sm font-medium">Причина изменения
                  <textarea className={`${inputClassName} min-h-24`} value={changeDraft.reason} maxLength={500} disabled={confirmLoading || confirmOutcomeUnknown} onChange={(event) => updateChangeDraft({ reason: event.target.value })} />
                </label>
              </>
            )}

            {previewLoading && <p role="status" className="text-sm text-muted-foreground">Сервер рассчитывает последствия…</p>}
            {previewError && <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{previewError}</p>}
            {confirmError && <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{confirmError}</p>}

            {preview && (
              <div className="space-y-4 rounded-xl border border-border p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><h3 className="font-semibold">Предпросмотр зафиксирован</h3><p className="text-xs text-muted-foreground">Действителен до {formatDateTime(preview.expires_at)}</p></div>
                  {expired && <span className="rounded-full bg-destructive/10 px-2 py-1 text-xs font-medium text-destructive">Срок истёк</span>}
                </div>
                <dl className="grid gap-3 text-sm sm:grid-cols-2">
                  <div><dt className="text-xs text-muted-foreground">Было</dt><dd>{formatPath(preview.from_path)}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Будет</dt><dd>{formatPath(preview.to_path)}</dd></div>
                  <div><dt className="text-xs text-muted-foreground">Затронуто сотрудников</dt><dd className="font-semibold">{preview.affected_employees}</dd></div>
                </dl>
                <div>
                  <h4 className="font-medium">Влияние на обучение</h4>
                  <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
                    <div>Будет добавлено: <strong>{preview.training.added}</strong></div>
                    <div>Больше не требуется: <strong>{preview.training.no_longer_required}</strong></div>
                    <div>Завершённое сохранено: <strong>{preview.training.preserved_completed}</strong></div>
                    <div>Другие источники сохранены: <strong>{preview.training.preserved_other_sources}</strong></div>
                  </dl>
                  {preview.training.courses.length > 0 && (
                    <ul className="mt-3 divide-y divide-border rounded-md border border-border">
                      {preview.training.courses.map((course) => (
                        <li key={course.course_id} className="p-3 text-sm">
                          <strong>{course.title}</strong>
                          <span className="mt-1 block text-xs text-muted-foreground">Новых назначений: {course.added}. Прежних назначений сохранено: {course.retained_previous}.</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground">«Больше не требуется» и «прежних назначений сохранено» означают утрату требования, а не удаление: все существующие назначения остаются без изменений.</p>
                </div>
                <div>
                  <h4 className="font-medium">Влияние на доступ к отчётам</h4>
                  {preview.reporting.length ? (
                    <ul className="mt-2 divide-y divide-border text-sm">
                      {preview.reporting.map((item) => <li key={item.user_id} className="py-2"><strong>{item.full_name}</strong><span className="block text-xs text-muted-foreground">Охват {item.before_count} → {item.after_count}; получено {item.gained}, потеряно {item.lost}</span></li>)}
                    </ul>
                  ) : <p className="mt-1 text-sm text-muted-foreground">Границы отчётности не изменятся.</p>}
                </div>
                {preview.warnings.length > 0 && <div className="rounded-md bg-amber-50 p-3 text-sm text-amber-900"><p className="flex items-center font-medium"><AlertTriangle className="mr-2 h-4 w-4" aria-hidden="true" />Предупреждения</p><ul className="mt-1 list-disc pl-5">{preview.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></div>}
              </div>
            )}

            {receipt && (
              <div className="rounded-xl border border-success/30 bg-success/5 p-4" role="status">
                <h3 className="font-semibold text-success">Изменение выполнено</h3>
                <p className="mt-2 text-sm">Затронуто сотрудников: {receipt.affected_employees}. Добавлено назначений: {receipt.added}. Сохранено назначений: {receipt.preserved}.</p>
                <p className="mt-1 text-xs text-muted-foreground">Выполнено {formatDateTime(receipt.executed_at)} · план {receipt.plan_id}</p>
              </div>
            )}

            <div className="flex flex-wrap justify-end gap-2 border-t border-border pt-4">
              <Button type="button" variant="ghost" disabled={confirmationLocked} onClick={closeChange}>{receipt ? 'Закрыть' : 'Отмена'}</Button>
              {!receipt && !preview && <Button type="button" disabled={!canPreview || previewLoading} onClick={requestPreview}>{previewLoading ? 'Расчёт…' : 'Получить предпросмотр'}</Button>}
              {preview && <Button type="button" disabled={(expired && !confirmOutcomeUnknown) || confirmLoading} onClick={confirmPreview}>{confirmLoading ? 'Подтверждение…' : confirmOutcomeUnknown ? 'Повторить подтверждение этого плана' : 'Подтвердить этот предпросмотр'}</Button>}
            </div>
          </div>
        )}
      </Modal>
    </section>
  );
}
