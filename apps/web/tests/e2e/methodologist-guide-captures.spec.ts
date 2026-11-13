import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { expect, test as base, type Page } from '@playwright/test';
import {
  appOrigin,
  assignment,
  audience,
  course,
  ids,
  lessons,
  quiz,
  sourceDocument,
  structure,
  SyntheticWorkspace,
  timestamp,
  trainingRows,
} from './learning-workspace-ux-fixtures';

// Synthetic guide recording on the real built application. Every API read is
// declared here; only fake commands armed immediately before a real UI action.
if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER || appOrigin !== 'http://127.0.0.1:3024') {
  throw new Error('Methodologist guide captures need the root-owned loopback 3024 app.');
}

const sourceSha256 = process.env.KAMILYA_GUIDE_SOURCE_SHA256;
if (!sourceSha256 || !/^[0-9a-f]{64}$/.test(sourceSha256)) {
  throw new Error('KAMILYA_GUIDE_SOURCE_SHA256 must be the root-computed exact src+build configuration sha256 (64 lowercase hex).');
}

const runId = `${process.env.KAMILYA_GUIDE_RUN_ID || new Date().toISOString().replace(/[:.]/g, '-')}-${process.pid}`;
const outDir = join(process.cwd(), '.release-evidence/guide-refresh-20261113/captures', runId);
const manifestPath = join(process.cwd(), 'scripts/docs/methodologist_walkthrough.json');
const captureManifestPath = join(outDir, 'capture-manifest.json');
const partialReceiptPath = join(outDir, 'capture-partial-receipt.json');
const sourceBaseline = '1ef4fb274b0bc37ac728eaa2402df3c70c16fafb';

const test = base.extend<{ workspace: SyntheticWorkspace }>({
  workspace: [async ({ context }, use) => {
    const workspace = new SyntheticWorkspace(context, 'ru');
    await workspace.install();
    await use(workspace);
    workspace.assertIsolated();
  }, { auto: true }],
});

test.use({ baseURL: appOrigin, serviceWorkers: 'block', viewport: { width: 1440, height: 1000 }, actionTimeout: 10_000, navigationTimeout: 15_000 });
test.setTimeout(45_000);

type Scene = {
  shotId: string;
  route: string;
  prepare?: (workspace: SyntheticWorkspace) => void;
  act: (page: Page, workspace: SyntheticWorkspace) => Promise<void>;
};

type VerifiedControl = { name: string; selector: string; boundingBox: { x: number; y: number; width: number; height: number } };

type CaptureReceipt = {
  shot_id: string;
  route: string;
  run_id: string;
  source_baseline: string;
  source_sha256: string;
  png_sha256: string;
  raw_png_sha256: string;
  viewport: { width: number; height: number };
  visible_controls_verified: true;
  verified_controls: VerifiedControl[];
  synthetic: true;
  manifest_sha256: string;
};

const existingEnrollment = {
  id: '71000000-0000-4000-8000-000000000021',
  course_id: ids.course,
  user_id: ids.existingLearner,
  status: 'completed',
  source: 'manual',
  enrolled_at: timestamp,
  completed_at: timestamp,
  progress_percent: 100,
};
const draft = { ...course, status: 'draft' as const, review_status: 'pending', ai_generated: false };
const reviewDraft = { ...draft, ai_generated: true, review_status: 'pending' as const };
const reviewApprovedDraft = { ...reviewDraft, review_status: 'approved' as const };
const approvedDraft = { ...draft, review_status: 'approved' as const };
const published = { ...course, status: 'published' as const, review_status: 'approved' as const };
const syntheticEmployee = {
  id: 'employee-synthetic-1',
  full_name: 'Синтетический сотрудник',
  personnel_number: 'SYN-001',
  is_active: true,
  organization_unit_id: 'unit-1',
  effective_unit_id: 'unit-1',
  placement_source: 'explicit',
  position_id: 'position-1',
  position_name: 'Оператор',
  hr_managed: false,
};
const staffOverview = {
  units: [
    { id: 'root-1', name: 'Головной офис', parent_id: null, unit_type: 'organization', is_active: true,
      is_head_office: true, head_user_id: null, breadcrumb: ['Головной офис'], direct_count: 0, subtree_count: 1, hr_managed: false },
    { id: 'unit-1', name: 'Учебное подразделение', parent_id: 'root-1', unit_type: 'department', is_active: true,
      is_head_office: false, head_user_id: null, breadcrumb: ['Головной офис', 'Учебное подразделение'], direct_count: 1, subtree_count: 1, hr_managed: false },
  ],
  positions: [{ id: 'position-1', name: 'Оператор', department_id: 'unit-1', is_active: true,
    employee_count: 1, unit_counts: { 'unit-1': 1 } }],
  total: 2,
  unplaced_count: 0,
};
const staffRoster = { items: [syntheticEmployee], total: 1, page: 1, page_size: 20 };
const sourceReview = {
  document_id: ids.document,
  document_version: 3,
  title: 'Синтетическая инструкция по охране труда',
  revision: 7,
  status: 'in_review' as const,
  error: null,
  questions: [{
    id: 'boundary', start: 0, end: 35,
    quote: 'До 45 МРП применяется порядок А.',
    reason: 'Что делать при 45 МРП?',
    resolution: null,
  }],
  automatic: [{ id: 'auto-1', start: 0, end: 35, before: 'До 45 МРП применяется порядок А.',
    after: 'До 45 МРП включительно применяется порядок А.', reason: 'Уточнение границы', undone: false }],
  original_text: 'До 45 МРП применяется порядок А.',
  working_text: 'До 45 МРП включительно применяется порядок А.',
  approval: null,
  journal: [{ id: 'journal-1', kind: 'automatic', revision: 7, actor_id: ids.author,
    created_at: timestamp, before: 'До 45 МРП', after: 'До 45 МРП включительно' }],
};
const groupedQuiz = {
  courses: [{
    ...draft,
    modules: [{
      ...structure.modules[0],
      lessons: [{
        ...lessons[0],
        quiz: {
          ...quiz,
          questions: quiz.questions.map((question) => ({
            ...question,
            type: 'MCQ',
            choices: question.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })),
          })),
        },
      }],
    }],
  }],
  orphans: [],
};
const syntheticPreviousEnrollmentId = '00000000-0000-4000-8000-000000000801';
const trainingFixtureRows = trainingRows.map((row, index) => index === 0 ? {
  ...row,
  full_name: 'Синтетический сотрудник',
  personnel_number: 'SYN-001',
  email: 'employee-1@example.invalid',
  enrollment_status: 'completed',
  completed_at: timestamp,
  computed_status: 'completed',
  progress_percent: 100,
  best_score: 100,
  quiz_attempts_count: 1,
  certificate_id: 'certificate-synthetic-1',
  certificate_number: 'SYN-CERT-001',
  certificate_issued_at: timestamp,
  certificate_status: 'issued',
  latest_evidence_event_id: ids.evidence,
  evidence_procedure_type: 'training',
  evidence_confirmation_status: 'confirmed',
  evidence_signed_copy_status: 'accepted',
  evidence_state: 'ready',
} : row);

const dashboardFixture = {
  summary: { training_log: { total: 1, assigned: 0, in_progress: 0, completed: 1, overdue: 0,
    failed_current: 0, exhausted_attempts: 0, reassigned: 0, cancelled_history: 0, superseded_history: 0 },
    training_issue_count: 1, training_issue_counts: { overdue: 1 }, training_items_truncated: false,
    weak_question_count: 0, action_count: 0, actions_truncated: false, open_action_count: 0, overdue_action_count: 0 },
  training_items: [{ enrollment_id: ids.enrollment, user_id: ids.learner,
    full_name: 'Сотрудник с риском', course_id: ids.course, course_title: course.title,
    issue_type: 'overdue', progress_percent: 25, best_score: null, quiz_attempts_count: 0,
    assignment_due_at: timestamp, active_action_id: null, active_action_types: [] }],
  weak_questions: [], actions: [],
};

const dashboardJobs = [
  { id: 'job-synthetic-1', job_type: 'course_generation', status: 'running', stage: 'generating',
    course_title: 'Новый учебный курс', created_at: timestamp },
  { id: 'job-synthetic-2', job_type: 'course_generation', status: 'failed', stage: 'review',
    course_title: 'Черновик требует проверки', created_at: timestamp },
];

const guideImportSessionId = 'guide-import-session-1';
const guideImportMapping = {
  personnel_number: 'Табельный номер',
  first_name: 'Имя',
  last_name: 'Фамилия',
  branch: 'Подразделение',
  department: 'Отдел',
  position: 'Должность',
};
const guideImportProposal = {
  branches: [
    { branch_id: 'root-1', branch_name: 'Головной офис', external_key: 'branch-1', action: 'unchanged', confidence: 'high', evidence: [] },
  ],
  departments: [
    { department_id: 'unit-1', department_name: 'Учебное подразделение', external_key: 'dept-1', branch_external_key: 'branch-1', action: 'create', confidence: 'high', evidence: [] },
  ],
  positions: [
    { position_id: 'position-1', position_name: 'Оператор', external_key: 'position-1', branch_external_key: 'branch-1', department_external_key: 'dept-1', action: 'create', confidence: 'high', evidence: [] },
  ],
  staff: [
    { external_key: 'staff-synthetic-1', personnel_number: 'SYN-001', first_name: 'Синтетический', last_name: 'Сотрудник', position_external_key: 'position-1', branch_external_key: 'branch-1', department_external_key: 'dept-1', action: 'create', confidence: 'high', evidence: [] },
  ],
  conflicts: [],
  summary: { branches: 1, departments: 1, positions: 1, staff: 1, conflicts: 0 },
};
const guideImportReady = {
  id: guideImportSessionId,
  state: 'ready_for_approval',
  mode: 'ADD_OR_UPDATE',
  source_file_name: 'synthetic-staff.xlsx',
  source_file_sha256: 'a'.repeat(64),
  source_format: 'xlsx',
  workbook_analysis: {
    parser: {
      raw_columns: ['Табельный номер', 'Имя', 'Фамилия', 'Подразделение', 'Отдел', 'Должность'],
      suggested_mapping: guideImportMapping,
      missing_required_columns: [],
      selected_sheet: 'Сотрудники',
      header_row: 1,
    },
  },
  mapping_json: guideImportMapping,
  proposal: guideImportProposal,
  proposal_revision: 'revision-1',
  expires_at: null,
  result_summary: null,
};
const guideImportApproved = { ...guideImportReady, state: 'approved' };
const guideImportCommitted = {
  ...guideImportApproved,
  state: 'committed',
  result_summary: { branches: 0, departments: 1, positions: 1, staff: 1, conflicts: 0 },
};

async function openRestoredImport(page: Page, workspace: SyntheticWorkspace, shotId: string) {
  workspace.get(`/v1/admin/staff/import/sessions/${guideImportSessionId}`, guideImportReady);
  await page.evaluate((sessionId) => {
    window.sessionStorage.setItem('kamilya-adaptive-import-session-id', sessionId);
  }, guideImportSessionId);
  await page.reload();
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
  await page.getByRole('tab', { name: 'Структура' }).click({ timeout: CONTROL_TIMEOUT_MS });
  await page.getByRole('button', { name: 'Импорт', exact: true }).click({ timeout: CONTROL_TIMEOUT_MS });
  await expect(page.getByRole('heading', { level: 1, name: 'Импорт сотрудников' })).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
  await expect(page.getByRole('heading', { name: 'Импорт из Excel или CSV' })).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
  await expect(page.getByText(/SYN-001/).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
  void shotId;
}

function installMethodologistImportReads(workspace: SyntheticWorkspace) {
  installMethodologistReads(workspace, 'staff');
  workspace.get(`/v1/admin/staff/import/sessions/${guideImportSessionId}`, guideImportReady);
}

function installMethodologistReads(workspace: SyntheticWorkspace, mode: 'dashboard' | 'documents' | 'review' | 'generation' | 'course' | 'staff' | 'assignments' | 'log') {
  workspace.role = 'methodologist';
  workspace.presentation = { tenantName: 'Учебная организация', fullName: 'Учебный методист' };

  if (mode === 'dashboard') {
    workspace.get('/v1/admin/onboarding-status', { steps: [] });
    workspace.get('/v1/admin/learning-actions', dashboardFixture);
    workspace.onGet('/v1/courses', ({ url }) => ({ json: url.searchParams.get('per_page') === '100' ? [course, draft] : [course] }));
    workspace.get('/v1/ai/jobs', dashboardJobs);
    workspace.get('/v1/admin/mandatory-training/summary', { total: 1, materialized: 0, missing_enrollment: 1,
      protected_assignment: 0, stale_managed_enrollment: 0, action_materialize: 1, action_review_stale: 0 });
  }

  if (mode === 'documents') {
    workspace.get('/v1/documents/catalog', { items: [sourceDocument], page: { next_cursor: null, has_more: false, limit: 25 } });
    workspace.get('/v1/youtube/limits', { enabled: false });
    workspace.get('/v1/admin/source-actuality', { items: [] });
    workspace.get(`/v1/documents/${ids.document}`, sourceDocument);
  }

  if (mode === 'review') {
    workspace.get(`/v1/documents/${ids.document}/editorial-review`, sourceReview);
    workspace.get(`/v1/documents/${ids.document}`, sourceDocument);
    workspace.get('/v1/courses', [draft]);
  }

  if (mode === 'generation') {
    workspace.onGet('/v1/documents/catalog', ({ url }) => ({ json: {
      items: [sourceDocument],
      page: { next_cursor: null, has_more: false, limit: url.searchParams.get('limit') === '100' ? 100 : 25 },
    } }));
    workspace.get('/v1/youtube/limits', { enabled: false });
    workspace.get('/v1/documents/editorial-review/status', { documents: [] });
  }

  if (mode === 'course') {
    workspace.get(`/v1/courses/${ids.course}`, draft);
    workspace.get(`/v1/courses/${ids.course}/structure`, structure);
    for (const lesson of lessons) workspace.get(`/v1/lessons/${lesson.id}`, lesson);
    workspace.get(`/v1/courses/${ids.course}/approval-policy`, { course_id: ids.course, requires_approval: false, review_enabled: true });
    workspace.get('/v1/courses', [draft]);
  }

  if (mode === 'staff') {
    workspace.get('/v1/organization-units/workspace', staffOverview);
    workspace.get('/v1/organization-units/employees', staffRoster);
    workspace.get('/v1/users', { users: audience, total: audience.length });
    workspace.get('/v1/courses', [course]);
    workspace.get('/v1/admin/staff/import/mappings', { mappings: [] });
    workspace.get('/v1/admin/training-log', { items: [], total: 0, limit: 100, offset: 0, reporting_scope: 'restricted' });
  }

  if (mode === 'assignments') {
    workspace.get('/v1/courses', [published]);
    workspace.get(`/v1/courses/${ids.course}`, published);
    workspace.get(`/v1/courses/${ids.course}/enrollments`, [{ ...existingEnrollment, course_id: ids.course, title: course.title,
      enrollment_status: 'in_progress', delivery_type: 'native', progress_percent: 0, total_lessons: 2, completed_lessons: 0,
      enrolled_at: timestamp, assignment_due_at: null, assignment_source: 'manual', can_resume: true,
      resume_href: `/courses/${ids.course}?lessonId=${ids.lesson}` }]);
    workspace.get('/v1/users', { users: audience, total: audience.length });
    workspace.get('/v1/learning-cycles', []);
    workspace.get('/v1/learning-cycles/occurrences', []);
    workspace.get(`/v1/courses/enrollments/${existingEnrollment.id}/access`, {
      enrollment_id: existingEnrollment.id, course_id: ids.course, user_id: ids.existingLearner,
      access_type: 'personal_link', email: 'graduate@example.invalid', pin_required: true,
      personal_link: 'synthetic-link-placeholder', pin: '••••', is_active: true,
    });
  }

  if (mode === 'log') {
    const matchesFilters = (row: (typeof trainingFixtureRows)[number], url: URL): boolean => {
      const search = url.searchParams.get('search')?.trim().toLowerCase() ?? '';
      if (search && !row.full_name.toLowerCase().includes(search) && !row.personnel_number.toLowerCase().includes(search)) {
        return false;
      }
      const status = url.searchParams.get('status');
      if (status && row.enrollment_status !== status && row.computed_status !== status) return false;
      const delivery = url.searchParams.get('delivery_type');
      if (delivery && row.delivery_type !== delivery) return false;
      const courseId = url.searchParams.get('course_id');
      if (courseId && row.course_id !== courseId) return false;
      return true;
    };
    const historyRow = trainingFixtureRows[0] ? {
      ...trainingFixtureRows[0],
      enrollment_id: syntheticPreviousEnrollmentId,
      enrollment_status: 'cancelled',
      computed_status: 'assigned',
      progress_percent: 0,
      completed_at: null,
      certificate_id: null,
      certificate_number: null,
      certificate_issued_at: null,
      certificate_status: 'none',
      latest_evidence_event_id: null,
      evidence_procedure_type: null,
      evidence_confirmation_status: 'not_required',
      evidence_signed_copy_status: 'awaiting_return',
      evidence_state: 'forming',
      evidence_events: [],
    } : null;
    workspace.get('/v1/courses', [course]);
    workspace.get('/v1/admin/onboarding-status', { steps: [] });
    workspace.get('/v1/admin/learning-actions', {
      summary: { training_log: null, training_issue_count: 0, training_issue_counts: {},
        training_items_truncated: false, weak_question_count: 0, action_count: 0, actions_truncated: false,
        open_action_count: 0, overdue_action_count: 0 },
      training_items: [], weak_questions: [], actions: [],
    });
    workspace.onGet('/v1/admin/training-log', ({ url }) => {
      const filtered = trainingFixtureRows.filter((row) => matchesFilters(row, url));
      const history = url.searchParams.get('history') === 'true';
      const rows = history && historyRow ? [filtered[0] ?? trainingFixtureRows[0], historyRow] : filtered;
      if (url.searchParams.get('format') === 'csv') {
        const csvRows = rows.map((row) => `${row.full_name},${row.course_title},${row.enrollment_status}`);
        return {
          contentType: 'text/csv; charset=utf-8',
          body: `\uFEFFEmployee,Course,Status\r\n${csvRows.join('\r\n')}\r\n`,
        };
      }
      const limit = Number(url.searchParams.get('limit') ?? 100);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      return { json: { items: rows.slice(offset, offset + limit), total: rows.length,
        limit, offset, reporting_scope: 'restricted' } };
    });
    workspace.onGet('/v1/admin/training-log/summary', ({ url }) => {
      const rows = trainingFixtureRows.filter((row) => matchesFilters(row, url));
      return { json: { total: rows.length, assigned: rows.filter((row) => row.computed_status === 'assigned').length,
        in_progress: rows.filter((row) => row.computed_status === 'in_progress').length,
        completed: rows.filter((row) => row.computed_status === 'completed').length,
        overdue: 0 } };
    });
    workspace.onGet(`/v1/training-evidence/events/${ids.evidence}/signed-scans`, () => ({
      json: {
        event_id: ids.evidence,
        status: 'accepted',
        scans: [{
          id: '00000000-0000-4000-8000-000000000802',
          original_filename: 'synthetic-signed-scan.pdf',
          content_type: 'application/pdf',
          uploaded_at: timestamp,
          status: 'accepted',
        }],
      },
    }));
    workspace.get(`/v1/training-evidence/events/${ids.evidence}`, {
      id: ids.evidence, enrollment_id: ids.enrollment, content_release_id: ids.revision,
      procedure_type: 'training', record_type: 'course_completion', related_event_id: null,
      occurred_at: timestamp, created_at: timestamp, confirmation_status: 'not_required',
      procedure_title: course.title, release_version: 3, release_sha256: 'b'.repeat(64),
      confirmation_statement: null, confirmation_object_version: null,
    });
  }
}

async function gotoAndSettle(page: Page, route: string) {
  await page.goto(route);
  await expect(page.locator('[data-redesign-page], [data-catalog-layout]').first()).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
}

const CONTROL_TIMEOUT_MS = 5_000;

async function assertAndPin(page: Page, locator: ReturnType<Page['locator']>, name: string): Promise<VerifiedControl> {
  await locator.scrollIntoViewIfNeeded({ timeout: CONTROL_TIMEOUT_MS });
  await expect(locator).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
  const box = await locator.boundingBox({ timeout: CONTROL_TIMEOUT_MS });
  if (!box) throw new Error(`Verified control ${name} has no bounding box`);
  return { name, selector: name, boundingBox: box };
}

async function verifyControls(page: Page, controls: Array<{ locator: ReturnType<Page['locator']>; name: string }>) {
  let viewport = page.viewportSize();
  if (!viewport) throw new Error('Capture verification requires an explicit viewport');
  const initialViewport = viewport;

  const topbar = page.locator('[data-workspace-topbar="true"]');
  const topbarCount = await topbar.count();

  const measure = async () => {
    const currentViewport = page.viewportSize();
    if (!currentViewport) throw new Error('Capture verification requires an explicit viewport');
    const topbarBox = topbarCount > 0 ? await topbar.first().boundingBox({ timeout: CONTROL_TIMEOUT_MS }) : null;
    const headerBottom = topbarBox ? Math.max(0, topbarBox.y + topbarBox.height) : 0;
    const requiredTopMargin = headerBottom + 8;
    const availableViewportHeight = currentViewport.height - headerBottom - 16;

    const measured: Array<{ control: { locator: ReturnType<Page['locator']>; name: string }; top: number; bottom: number }> = [];
    for (const control of controls) {
      await control.locator.scrollIntoViewIfNeeded({ timeout: CONTROL_TIMEOUT_MS });
      await expect(control.locator).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      const bounds = await control.locator.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        return { top: rect.top + window.scrollY, bottom: rect.bottom + window.scrollY };
      });
      measured.push({ control, top: bounds.top, bottom: bounds.bottom });
    }

    const top = Math.min(...measured.map((entry) => entry.top));
    const bottom = Math.max(...measured.map((entry) => entry.bottom));
    return { currentViewport, headerBottom, requiredTopMargin, availableViewportHeight, measured, top, bottom, requiredSpan: bottom - top };
  };

  let frame = await measure();
  if (frame.requiredSpan > frame.availableViewportHeight) {
    const requestedHeight = Math.ceil(frame.requiredSpan + frame.headerBottom + 24);
    const nextHeight = Math.min(1600, requestedHeight);
    if (nextHeight < requestedHeight) {
      throw new Error(
        `Required controls need ${requestedHeight}px viewport height but capture is bounded to 1600px: required span ${frame.requiredSpan}px, top bar bottom ${frame.headerBottom}px`,
      );
    }
    await page.setViewportSize({ width: initialViewport.width, height: nextHeight });
    viewport = page.viewportSize() ?? { width: initialViewport.width, height: nextHeight };
    frame = await measure();
    if (frame.requiredSpan > frame.availableViewportHeight) {
      throw new Error(
        `Required controls do not fit below the sticky top bar after viewport resize: required span ${frame.requiredSpan}px exceeds available viewport height ${frame.availableViewportHeight}px (viewport ${viewport.height}px, top bar bottom ${frame.headerBottom}px)`,
      );
    }
  }

  await page.evaluate((scrollTop) => window.scrollTo(0, scrollTop), Math.floor(Math.max(0, frame.top - frame.requiredTopMargin)));

  const verified: VerifiedControl[] = [];
  await expect(async () => {
    const currentViewport = page.viewportSize();
    if (!currentViewport) throw new Error('Capture verification requires an explicit viewport');
    const currentTopbarBox = topbarCount > 0 ? await topbar.first().boundingBox({ timeout: CONTROL_TIMEOUT_MS }) : null;
    const currentHeaderBottom = currentTopbarBox ? Math.max(0, currentTopbarBox.y + currentTopbarBox.height) : 0;
    const currentRequiredTop = currentHeaderBottom + 8;

    const nextVerified: VerifiedControl[] = [];
    for (const control of controls) {
      const box = await control.locator.boundingBox({ timeout: CONTROL_TIMEOUT_MS });
      if (!box) throw new Error(`Verified control ${control.name} has no bounding box`);

      const insideX = box.x >= 0 && box.x + box.width <= currentViewport.width;
      const insideY = box.y >= currentRequiredTop && box.y + box.height <= currentViewport.height;
      if (!insideX || !insideY) {
        throw new Error(
          `${control.name} must be inside the final captured viewport below the sticky top bar: ` +
            `x=${box.x}..${box.x + box.width}, y=${box.y}..${box.y + box.height}, ` +
            `required y=${currentRequiredTop}..${currentViewport.height}`,
        );
      }

      const hit = await control.locator.evaluate((node) => {
        const rect = node.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const element = document.elementFromPoint(centerX, centerY);
        if (!element) return { ok: false, tag: '', id: '', className: '' };
        const ok = element === node || node.contains(element) || (node instanceof HTMLButtonElement && node.disabled && element !== document.body && element !== document.documentElement && element.contains(node));
        return { ok, tag: element.tagName.toLowerCase(), id: element.id, className: typeof element.className === 'string' ? element.className : '' };
      });
      if (!hit.ok) {
        throw new Error(`${control.name} center is occluded by the sticky top bar or another overlay (hit ${hit.tag}#${hit.id}.${hit.className})`);
      }

      nextVerified.push({ name: control.name, selector: control.name, boundingBox: box });
    }

    verified.splice(0, verified.length, ...nextVerified);
  }).toPass({ timeout: CONTROL_TIMEOUT_MS });

  return verified;
}

async function saveShot(page: Page, shotId: string, rawPath: string) {
  await page.screenshot({ path: rawPath, fullPage: false, animations: 'disabled' });
  const raw = await readFile(rawPath);
  const shotPath = join(outDir, `${shotId}.png`);
  await writeFile(shotPath, raw);
  return createHash('sha256').update(raw).digest('hex');
}

function resolveRoute(route: string) {
  return route
    .replace(':id', ids.course)
    .replace(':lessonId', ids.lesson)
    .replace(':documentId', ids.document);
}

const scenes: Scene[] = [
  { shotId: 'm01-s01-dashboard-tasks', route: '/dashboard', prepare: (w) => installMethodologistReads(w, 'dashboard'),
    act: async (page) => {
      const row = page.getByRole('button', { name: /Сотрудник с риском/ });
      await expect(row).toBeVisible();
      await row.click();
      await expect(page.getByRole('button', { name: /Сотрудник с риском/ })).toBeVisible();
      await expect(page.getByText('Срок обучения', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('25%', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm01-s02-document-upload', route: '/documents', prepare: (w) => installMethodologistReads(w, 'documents'),
    act: async (page) => {
      await page.getByRole('button', { name: /Загрузить документ/ }).first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await expect(dialog.getByText('Перетащите файл сюда или нажмите для выбора', { exact: true })).toBeVisible();
      await dialog.locator('input[type="file"]').setInputFiles({
        name: 'synthetic-upload.txt', mimeType: 'text/plain', buffer: Buffer.from('Synthetic upload content.'),
      });
      await expect(dialog.getByText('synthetic-upload.txt', { exact: true })).toBeVisible();
      await dialog.getByRole('textbox', { name: 'Название' }).fill('Synthetic safety instruction');
      await expect(dialog.getByRole('textbox', { name: 'Название' })).toHaveValue('Synthetic safety instruction');
    } },
  { shotId: 'm01-s03-upload-completion', route: '/documents', prepare: (w) => installMethodologistReads(w, 'documents'),
    act: async (page, workspace) => {
      const uploadBuffer = Buffer.from('Synthetic upload content.');
      const uploadedDocument = { ...sourceDocument, title: 'Synthetic safety instruction',
        filename: 'synthetic-upload.txt', content_type: 'text/plain', size: uploadBuffer.byteLength,
        description: 'Synthetic text source; all fragments indexed.',
        index: { status: 'ready', error_code: null, message: 'All fragments indexed.',
          chunks_total: 1, chunks_indexed: 1, indexed_at: timestamp, revision: 8 } };
      await page.getByRole('button', { name: /Загрузить документ/ }).first().click();
      const dialog = page.getByRole('dialog');
      await dialog.locator('input[type="file"]').setInputFiles({
        name: 'synthetic-upload.txt', mimeType: 'text/plain', buffer: uploadBuffer,
      });
      await dialog.getByRole('textbox', { name: 'Название' }).fill('Synthetic safety instruction');
      workspace.command('POST', '/v1/documents/upload', () => ({ json: uploadedDocument }));
      workspace.get('/v1/documents/catalog', { items: [uploadedDocument], page: { next_cursor: null, has_more: false, limit: 25 } });
      await dialog.getByRole('button', { name: 'Загрузить документ', exact: true }).click();
      await expect(dialog).toBeHidden();
      await expect(page.getByText('Synthetic safety instruction', { exact: true }).first()).toBeVisible();
      const documentRow = page.getByRole('button', { name: 'Synthetic safety instruction', exact: true }).locator('xpath=ancestor::div[contains(@class,"border-b")][1]');
      await expect(documentRow.getByText(/synthetic-upload\.txt\s*·\s*25 B/).first()).toBeVisible();
      await expect(documentRow.getByText(/25 B/).first()).toBeVisible();
      await expect(documentRow.getByText('Готов', { exact: true })).toBeVisible();
    } },
  { shotId: 'm01-s04-source-review', route: '/documents/:documentId/editorial-review', prepare: (w) => installMethodologistReads(w, 'review'),
    act: async (page) => {
      const openSummary = async (label: string) => {
        const summary = page.getByText(label, { exact: true }).first();
        await expect(summary).toBeVisible();
        const details = summary.locator('xpath=ancestor::details[1]');
        if (await details.count()) {
          const isOpen = await details.evaluate((el) => (el as HTMLDetailsElement).open);
          if (!isOpen) await summary.click();
        }
      };

      await expect(page.getByText('Проверка документа', { exact: true }).first()).toBeVisible();
      await openSummary('Вопросы к источнику');
      await openSummary('Оригинальный текст');
      await openSummary('Рабочая редакция');

      await expect(page.getByText('Вопросы к источнику', { exact: true })).toBeVisible();
      await expect(page.getByText('Оригинальный текст', { exact: true })).toBeVisible();
      await expect(page.getByText('Рабочая редакция', { exact: true })).toBeVisible();
      await expect(page.locator('pre').filter({ hasText: /^До 45 МРП применяется порядок А\.$/ })).toBeVisible();
      await expect(page.locator('pre').filter({ hasText: /^До 45 МРП включительно применяется порядок А\.$/ })).toBeVisible();

      const approveButton = page.getByRole('button', { name: 'Утвердить редакцию' });
      await expect(approveButton).toBeVisible();
      await expect(approveButton).toBeDisabled();
    } },
  { shotId: 'm01-s05-source-history', route: '/documents/:documentId/editorial-review', prepare: (w) => installMethodologistReads(w, 'review'),
    act: async (page) => {
      const openSummary = async (label: string) => {
        const summary = page.getByText(label, { exact: true }).first();
        await expect(summary).toBeVisible();
        const details = summary.locator('xpath=ancestor::details[1]');
        if (await details.count()) {
          const isOpen = await details.evaluate((el) => (el as HTMLDetailsElement).open);
          if (!isOpen) await summary.click();
        }
      };

      const journalHeading = page.getByText('Журнал правок', { exact: true });
      await journalHeading.scrollIntoViewIfNeeded();
      await expect(journalHeading).toBeVisible();

      const journalRow = page.getByText(/До 45 МРП включительно/, { exact: false }).first();
      await journalRow.scrollIntoViewIfNeeded();
      await expect(journalRow).toBeVisible();

      await openSummary('Оригинальный текст');
      await openSummary('Рабочая редакция');

      await expect(page.getByText('Оригинальный текст', { exact: true })).toBeVisible();
      await expect(page.getByText('Рабочая редакция', { exact: true })).toBeVisible();
      await expect(page.locator('pre').filter({ hasText: /^До 45 МРП применяется порядок А\.$/ })).toBeVisible();
      await expect(page.locator('pre').filter({ hasText: /^До 45 МРП включительно применяется порядок А\.$/ })).toBeVisible();
      await expect(page.getByText(/Версия документа|Редакция|редакция/).first()).toBeVisible();
    } },
  { shotId: 'm02-s01-document-selection', route: '/ai/generate?new=1', prepare: (w) => installMethodologistReads(w, 'generation'),
    act: async (page, workspace) => {
      await expect(page.getByRole('searchbox', { name: 'Поиск по документам' })).toBeVisible();
      await expect(page.getByText('Synthetic safety instruction', { exact: true }).first()).toBeVisible();
      workspace.command('POST', '/v1/ai/document-compatibility', () => ({ json: {
        status: 'compatible', score: 1, requires_decision: false, clusters: [],
      } }));
      const documentCheckbox = page.getByRole('checkbox', { name: 'Выбрать документ Synthetic safety instruction' });
      await documentCheckbox.check();
      await expect(documentCheckbox).toBeChecked();
      await expect(page.getByText('Загруженные документы (1 документ выбрано)', { exact: true })).toBeVisible();
      await expect(page.getByText('Документы образуют одну тематическую группу. Можно проектировать единый курс.', { exact: true })).toBeVisible();
    } },
  { shotId: 'm02-s02-generation-settings', route: '/ai/generate?new=1', prepare: (w) => installMethodologistReads(w, 'generation'),
    act: async (page, workspace) => {
      workspace.command('POST', '/v1/ai/document-compatibility', () => ({ json: {
        status: 'compatible', score: 1, requires_decision: false, clusters: [],
      } }));
      await page.getByRole('checkbox', { name: 'Выбрать документ Synthetic safety instruction' }).check();
      await expect(page.getByRole('checkbox', { name: 'Выбрать документ Synthetic safety instruction' })).toBeChecked();
      const freshTimestamp = new Date().toISOString();
      workspace.command('POST', '/v1/ai/generate-course', () => ({ status: 202, json: {
        id: 'job-synthetic-1', status: 'running', course_id: null, created_at: timestamp,
        updated_at: freshTimestamp, progress: 10, stage: 'generating', message: '',
        queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: 1, tenant_active_limit: 3,
        abandon_available: false,
      } }));
      workspace.get('/v1/ai/jobs/job-synthetic-1', { id: 'job-synthetic-1', status: 'running', course_id: null,
        created_at: timestamp, updated_at: freshTimestamp, progress: 10, stage: 'generating', message: '',
        queue_position: null, estimated_wait_seconds: null, tenant_active_jobs: 1, tenant_active_limit: 3,
        abandon_available: false });
      const generate = page.getByRole('button', { name: /Генерировать курс/ }).first();
      await expect(generate).toBeEnabled();
      await generate.click();
      await expect(page.getByText('Прогресс генерации', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm02-s03-job-state', route: '/courses/:id/edit', prepare: (w) => installMethodologistReads(w, 'course'),
    act: async (page) => {
      await expect(page.getByText('Synthetic workplace safety', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Safe work', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Prepare safely', { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/черновик|Черновик/i).first()).toBeVisible();
    } },
  { shotId: 'm02-s04-saved-job-link', route: '/dashboard', prepare: (w) => installMethodologistReads(w, 'dashboard'),
    act: async (page) => {
      await expect(page.getByText('Задания генерации', { exact: true }).first()).toBeVisible();
      const jobRow = page.getByRole('button', { name: /Новый учебный курс.*заявка job-syn/ });
      await expect(jobRow).toBeVisible();
      await jobRow.click();
      await expect(page.getByRole('heading', { name: 'Детали задачи', exact: true }).first()).toBeVisible();
      const jobLink = page.getByRole('link', { name: 'Открыть задание генерации', exact: true });
      await expect(jobLink).toBeVisible();
      await expect(jobLink).toHaveAttribute('href', '/ai/generate?job_id=job-synthetic-1');
    } },
  { shotId: 'm03-s01-editor-lesson-select', route: '/courses/:id/edit', prepare: (w) => installMethodologistReads(w, 'course'),
    act: async (page) => {
      await expect(page.getByText('Safe work', { exact: true }).first()).toBeVisible();
      await page.getByRole('button', { name: 'Prepare safely', exact: true }).first().click();
      await expect(page.getByRole('textbox', { name: 'Содержание урока' })).toBeVisible();
    } },
  { shotId: 'm03-s02-illustration-source-link', route: '/courses/:id/edit', prepare: (w) => installMethodologistReads(w, 'course'),
    act: async (page) => {
      await page.getByRole('button', { name: 'Prepare safely', exact: true }).first().click();
      await expect(page.getByRole('textbox', { name: 'Содержание урока' })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Открыть как обучающийся', exact: true })).toBeVisible();
    } },
  { shotId: 'm03-s03-preview-lesson', route: '/courses/:id/edit', prepare: (w) => installMethodologistReads(w, 'course'),
    act: async (page) => {
      await page.getByRole('button', { name: 'Prepare safely', exact: true }).first().click();
      await page.getByRole('button', { name: 'Предпросмотр', exact: true }).click();
      const preview = page.locator('article').last();
      await expect(preview.getByRole('heading', { name: 'Prepare safely', exact: true })).toBeVisible();
      await expect(preview.getByText('Read the safety instructions before starting.', { exact: true })).toBeVisible();
      await expect(preview.getByRole('heading', { name: 'Before work', exact: true })).toBeVisible();
      await expect(preview.getByText('Inspect equipment.', { exact: true })).toBeVisible();
      await expect(preview.getByText('Report damage.', { exact: true })).toBeVisible();
    } },
  { shotId: 'm03-s04-save-reopen-lesson', route: '/courses/:id/edit', prepare: (w) => installMethodologistReads(w, 'course'),
    act: async (page, workspace) => {
      const editedContent = `${lessons[0].content}\n\nСинтетическая проверка читаемости.`;
      const savedLesson = { ...lessons[0], content: editedContent };
      await page.getByRole('button', { name: 'Prepare safely', exact: true }).first().click();
      const editor = page.getByRole('textbox', { name: 'Содержание урока' });
      await editor.fill(editedContent);
      workspace.command('PATCH', `/v1/lessons/${ids.lesson}`, () => ({ json: savedLesson }));
      workspace.get(`/v1/lessons/${ids.lesson}`, savedLesson);
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(page.getByText('Сохранено', { exact: true }).first()).toBeVisible();
      await page.getByRole('button', { name: 'Report a hazard', exact: true }).first().click();
      await expect(editor).toHaveValue(lessons[1].content);
      await page.getByRole('button', { name: 'Prepare safely', exact: true }).first().click();
      await expect(editor).toHaveValue(editedContent);
      await page.getByRole('button', { name: 'Предпросмотр', exact: true }).click();
      const preview = page.locator('article').last();
      await expect(preview.getByText('Синтетическая проверка читаемости.', { exact: true })).toBeVisible();
      await expect(preview.getByText('Read the safety instructions before starting.', { exact: true })).toBeVisible();
    } },
  { shotId: 'm04-s01-open-test', route: '/quizzes?lessonId=:lessonId', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get('/v1/quizzes/grouped', groupedQuiz);
      w.get(`/v1/quizzes/${ids.quiz}`, quiz);
    },
    act: async (page) => {
      await expect(page.getByText('Тесты и вопросы', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Safety knowledge check', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Вопросы', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('What should you do with damaged equipment?', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm04-s02-learner-wording', route: '/quizzes?lessonId=:lessonId', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get('/v1/quizzes/grouped', groupedQuiz);
    },
    act: async (page) => {
      await page.getByRole('button', { name: /Редактировать/ }).first().click();
      await expect(page.getByRole('textbox', { name: 'Текст вопроса' })).toBeVisible();
      await expect(page.getByText('Варианты ответа', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Пояснение после ответа', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm04-s03-preserve-good-parts', route: '/quizzes?lessonId=:lessonId', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get('/v1/quizzes/grouped', groupedQuiz);
    },
    act: async (page, workspace) => {
      const updatedQuestion = 'Что нужно сделать с повреждённым оборудованием?';
      await page.getByRole('button', { name: /Редактировать/ }).first().click();
      await page.getByRole('textbox', { name: 'Текст вопроса' }).fill(updatedQuestion);
      workspace.command('PUT', `/v1/quizzes/${ids.quiz}/questions/${ids.question}`, () => ({ json: {
        ...quiz, questions: quiz.questions.map((question) => ({ ...question,
          text: updatedQuestion, type: 'MCQ',
          choices: question.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })) })) } }));
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(page.getByText(/Вопрос обновлён|Сохранено/).first()).toBeVisible();
      await expect(page.getByText(updatedQuestion, { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm04-s04-reopen-saved-test', route: '/quizzes?lessonId=:lessonId', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get('/v1/quizzes/grouped', groupedQuiz);
      w.get(`/v1/quizzes/${ids.quiz}`, quiz);
    },
    act: async (page, workspace) => {
      const updatedQuestion = 'Что нужно сделать с повреждённым оборудованием?';
      await expect(page.getByText('Вопросы', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('What should you do with damaged equipment?', { exact: true }).first()).toBeVisible();
      await page.getByRole('button', { name: /Редактировать/ }).first().click();
      await page.getByRole('textbox', { name: 'Текст вопроса' }).fill(updatedQuestion);
      workspace.command('PUT', `/v1/quizzes/${ids.quiz}/questions/${ids.question}`, () => ({ json: {
        ...quiz, questions: quiz.questions.map((question) => ({ ...question,
          text: updatedQuestion, type: 'MCQ',
          choices: question.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })) })) } }));
      await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
      await expect(page.getByText(/Вопрос обновлён|Сохранено/).first()).toBeVisible();
      await expect(page.getByText(updatedQuestion, { exact: true }).first()).toBeVisible();
      await page.getByRole('button', { name: /Редактировать/ }).first().click();
      await expect(page.getByRole('textbox', { name: 'Текст вопроса' })).toHaveValue(updatedQuestion);
    } },
  { shotId: 'm05-s01-review-before-approval', route: '/courses/:id/edit', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get(`/v1/courses/${ids.course}`, reviewDraft);
    },
    act: async (page) => {
      const checks = page.locator('[data-publication-checks]');
      await expect(checks.locator('summary')).toContainText('Проверка и публикация — подробности');
      await checks.locator('summary').click();
      await expect(page.getByRole('button', { name: 'Открыть замечания и источники' })).toBeVisible();
    } },
  { shotId: 'm05-s02-approve-course', route: '/courses/:id/edit', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get(`/v1/courses/${ids.course}`, reviewDraft);
    },
    act: async (page, workspace) => {
      await page.locator('[data-publication-checks] summary').click();
      await expect(page.getByRole('button', { name: 'Одобрить курс', exact: true })).toBeVisible();
      workspace.command('POST', `/v1/courses/${ids.course}/review`, () => ({ json: reviewApprovedDraft }));
      await page.getByRole('button', { name: 'Одобрить курс', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Опубликовать', exact: true })).toBeVisible();
    } },
  { shotId: 'm05-s03-publish-separately', route: '/courses/:id/edit', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get(`/v1/courses/${ids.course}`, reviewApprovedDraft);
    },
    act: async (page, workspace) => {
      await page.locator('[data-publication-checks] summary').click();
      await expect(page.getByRole('button', { name: 'Опубликовать', exact: true })).toBeVisible();
      workspace.command('POST', `/v1/courses/${ids.course}/publish`, () => ({ json: published }));
      await page.getByRole('button', { name: 'Опубликовать', exact: true }).click();
      await expect(page.getByRole('group', { name: 'Редактировать курс' }).getByText('Опубликован', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm05-s04-published-state', route: '/courses', prepare: (w) => {
      installMethodologistReads(w, 'course');
      w.get('/v1/courses', [published]);
      w.get('/v1/course-blueprints', []);
    },
    act: async (page) => {
      const card = page.getByRole('region', { name: 'Открыть курс' });
      await expect(card.getByText('Synthetic workplace safety', { exact: true }).first()).toBeVisible();
      await expect(card.getByText(/Опубликован/).first()).toBeVisible();
      await expect(card.getByRole('link', { name: 'Назначить сотрудникам' })).toBeVisible();
    } },
  { shotId: 'm06-s01-staff-list', route: '/admin/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1', prepare: (w) => installMethodologistReads(w, 'staff'),
    act: async (page) => {
      await expect(page.getByRole('tab', { name: 'Список' })).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Структура' })).toBeVisible();
      await expect(page.getByText('Синтетический сотрудник', { exact: true }).first()).toBeVisible();
      await expect(page.getByText(/Доступ к кабинету/).first()).toBeVisible();
    } },
  { shotId: 'm06-s02-structure-add-unit', route: '/admin/staff?tab=structure&staff_view=schema&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1', prepare: (w) => installMethodologistReads(w, 'staff'),
    act: async (page) => {
      await page.getByRole('tab', { name: 'Структура' }).click();
      await page.getByRole('button', { name: /Добавить подразделение/ }).first().click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.getByText(/Тип подразделения/).first()).toBeVisible();
      await expect(page.getByText(/Вышестоящее подразделение|Корневое подразделение/).first()).toBeVisible();
    } },
  { shotId: 'm06-s03-import-preview', route: '/admin/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1', prepare: (w) => installMethodologistImportReads(w),
    act: async (page, workspace) => {
      await openRestoredImport(page, workspace, 'm06-s03-import-preview');
      await expect(page.getByText(/Сопоставление/).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      await expect(page.getByText(/Предложение/).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      await expect(page.getByText(/Конфликты/).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      await expect(page.getByText(/SYN-001/).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      await expect(page.getByText('Учебное подразделение', { exact: true }).first()).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
    } },
  { shotId: 'm06-s04-import-apply-verify', route: '/admin/staff?tab=structure&staff_view=people&staff_unit=all&staff_scope=subtree&staff_access=active&staff_page=1', prepare: (w) => installMethodologistImportReads(w),
    act: async (page, workspace) => {
      await openRestoredImport(page, workspace, 'm06-s04-import-apply-verify');
      const approve = page.getByRole('button', { name: 'Подтвердить предложение', exact: true });
      await expect(approve).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
      workspace.command('POST', `/v1/admin/staff/import/sessions/${guideImportSessionId}/approve`, () => ({ json: guideImportApproved }));
      await approve.click({ timeout: CONTROL_TIMEOUT_MS });
      const commit = page.getByRole('button', { name: 'Применить подтверждённые изменения', exact: true });
      await expect(commit).toBeEnabled({ timeout: CONTROL_TIMEOUT_MS });
      workspace.command('POST', `/v1/admin/staff/import/sessions/${guideImportSessionId}/commit`, () => ({ json: guideImportCommitted }));
      await commit.click({ timeout: CONTROL_TIMEOUT_MS });
      await page.getByRole('button', { name: 'К сотрудникам', exact: true }).click({ timeout: CONTROL_TIMEOUT_MS });
      await page.getByRole('tab', { name: 'Список' }).click({ timeout: CONTROL_TIMEOUT_MS });
      const employeeRow = page.getByRole('button', { name: /Синтетический сотрудник.*Учебное подразделение/ });
      await expect(employeeRow).toBeVisible({ timeout: CONTROL_TIMEOUT_MS });
    } },
  { shotId: 'm07-s01-course-assign-entry', route: '/assignments?courseId=:id', prepare: (w) => installMethodologistReads(w, 'assignments'),
    act: async (page) => {
      await expect(page.getByText('Назначить', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Текущие назначения', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Курс: Synthetic workplace safety', { exact: true }).first()).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Обучающиеся', exact: true })).toBeVisible();
    } },
  { shotId: 'm07-s02-mode-assign', route: '/assignments?courseId=:id', prepare: (w) => installMethodologistReads(w, 'assignments'),
    act: async (page) => {
      await expect(page.getByText('Назначить', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Текущие назначения', { exact: true }).first()).toBeVisible();
      await expect(page.getByText('Курс: Synthetic workplace safety', { exact: true }).first()).toBeVisible();
      await expect(page.getByRole('heading', { name: 'Обучающиеся', exact: true })).toBeVisible();
    } },
  { shotId: 'm07-s03-recipient-delivery-pin', route: '/assignments?courseId=:id', prepare: (w) => installMethodologistReads(w, 'assignments'),
    act: async (page) => {
      await expect(page.getByRole('heading', { name: 'Обучающиеся', exact: true })).toBeVisible();
      await page.getByRole('checkbox', { name: 'Synthetic Learner' }).check();
      await page.getByRole('radio', { name: /^Персональная ссылка и PIN/ }).check();
      await expect(page.getByRole('radio', { name: /^Email/ })).toBeVisible();
    } },
  { shotId: 'm07-s04-confirm-current-record', route: '/assignments?courseId=:id', prepare: (w) => {
      installMethodologistReads(w, 'assignments');
      let created = false;
      const accessUrl = 'https://example.invalid/personal-link';
      const existing = { ...existingEnrollment, title: course.title };
      w.onGet(`/v1/courses/${ids.course}/enrollments`, () => ({
        json: created
          ? [existing, {
              id: ids.enrollment, course_id: ids.course, user_id: ids.learner,
              status: 'enrolled', source: 'manual', enrolled_at: timestamp,
              completed_at: null, progress_percent: 0,
            }]
          : [existing],
      }));
      w.command('POST', `/v1/courses/${ids.course}/personal-link-enrollment`, (call) => {
        const body = call.body as { user_id?: string } | undefined;
        expect(body?.user_id).toBe(ids.learner);
        created = true;
        return {
          json: {
            enrollment_id: ids.enrollment,
            access_url: accessUrl,
            temporary_pin: '123456',
            expires_at: timestamp,
            link_expires_at: timestamp,
            completion_window_minutes: 10,
          },
        };
      });
      w.onGet(`/v1/courses/enrollments/${ids.enrollment}/access`, () => ({
        json: {
          enrollment_id: ids.enrollment,
          user_id: ids.learner,
          access_kind: 'personal_link',
          state: 'available',
          access_url: accessUrl,
          expires_at: timestamp,
          message: 'Personal link',
        },
      }));
    },
    act: async (page) => {
      await page.getByRole('checkbox', { name: /Synthetic Learner/ }).first().check();
      await page.getByRole('radio', { name: /^Персональная ссылка и PIN/ }).first().check();
      await page.getByRole('button', { name: /Назначить \(1\)/ }).first().click();
      const dialog = page.getByRole('dialog');
      await expect(dialog).toBeVisible();
      await dialog.getByRole('button', { name: 'Назначить', exact: true }).click();
      await expect(page.getByText(/PIN:/).first()).toBeVisible();
      await page.goto(`/assignments?courseId=${ids.course}&enrollment_id=${ids.enrollment}`);
      await expect(page.getByText('Synthetic Learner', { exact: true }).first()).toBeVisible();
      await expect(page.getByRole('button', { name: 'Получить ссылку', exact: true }).first()).toBeVisible();
      await expect(page.getByText(/PIN:/)).toHaveCount(0);
    } },
  { shotId: 'm08-s01-person-search', route: '/training-log', prepare: (w) => installMethodologistReads(w, 'log'),
    act: async (page) => {
      const search = page.getByRole('textbox', { name: 'Поиск' });
      await search.fill('SYN-001');
      await expect(search).toHaveValue('SYN-001');
      await expect(page.getByRole('button', { name: /Синтетический сотрудник/ }).first()).toBeVisible();
      await expect(page.getByText(/Всего записей:\s*1\b/).first()).toBeVisible();
      await expect(page.getByText(/фильтр/i).first()).toBeVisible();
    } },
  { shotId: 'm08-s02-training-completion', route: '/training-log', prepare: (w) => installMethodologistReads(w, 'log'),
    act: async (page) => {
      await page.getByText('Синтетический сотрудник', { exact: true }).first().click();
      await expect(page.getByRole('heading', { name: 'Синтетический сотрудник', exact: true })).toBeVisible();
      await expect(page.getByText(/Завершён/).first()).toBeVisible();
      await expect(page.getByText(/Прогресс: 100%/).first()).toBeVisible();
      await expect(page.getByText('SYN-CERT-001', { exact: true }).first()).toBeVisible();
    } },
  { shotId: 'm08-s03-signed-copy-state', route: '/training-log', prepare: (w) => installMethodologistReads(w, 'log'),
    act: async (page) => {
      const search = page.getByRole('textbox', { name: 'Поиск' });
      await search.fill('Синтетический сотрудник');
      await expect(search).toHaveValue('Синтетический сотрудник');
      await expect(page.getByText(/Всего записей:\s*1\b/).first()).toBeVisible();
      const history = page.getByRole('checkbox', { name: 'Включить историю назначений' });
      await history.click();
      await expect(history).toBeChecked();
      await expect(page).toHaveURL(/[?&]history=true(?:&|$)/);
      await expect(page.getByText(/Всего записей:\s*2\b/).first()).toBeVisible();
      const completedRow = page.getByRole('button', { name: /Синтетический сотрудник.*Завершён/ }).first();
      const historicalRow = page.getByRole('button', { name: /Синтетический сотрудник.*0%/ }).first();
      await expect(completedRow).toBeVisible();
      await expect(historicalRow).toBeVisible();
      await historicalRow.click();
      const detail = page.getByRole('region', { name: 'Журнал обучения' });
      await expect(detail.getByText(/Отмен/).first()).toBeVisible();
      await completedRow.click();
      await expect(detail.getByText('Подписанный экземпляр принят', { exact: true }).first()).toBeVisible();
      await expect(history).toBeChecked();
      await expect(page.getByText(/Всего записей:\s*2\b/).first()).toBeVisible();
      await expect(completedRow).toBeVisible();
      await expect(historicalRow).toBeVisible();
    } },
  { shotId: 'm08-s04-csv-export-scope', route: '/training-log', prepare: (w) => installMethodologistReads(w, 'log'),
    act: async (page) => {
      const downloadPromise = page.waitForEvent('download');
      await page.getByRole('button', { name: /CSV/ }).first().click();
      const download = await downloadPromise;
      const stream = await download.createReadStream();
      let csv = '';
      for await (const chunk of stream) csv += chunk.toString('utf8');
      const lines = csv.split(/\r?\n/).filter((line) => line.trim().length > 0);
      expect(lines).toHaveLength(103);
      expect(lines[0]).toContain('Employee,Course,Status');
      expect(lines[1]).toContain('Синтетический сотрудник');
    } },
];

const controlAssertions = (page: Page, scene: Scene) => {
  if (scene.shotId === 'm01-s01-dashboard-tasks') return [
    { locator: page.getByRole('button', { name: /Сотрудник с риском/ }), name: 'Сотрудник с риском' },
    { locator: page.getByText('Срок обучения', { exact: true }).first(), name: 'Срок обучения' },
    { locator: page.getByText('25%', { exact: true }).first(), name: '25%' },
    { locator: page.getByText('Задания генерации', { exact: true }).first(), name: 'Задания генерации' },
  ];
  if (scene.shotId === 'm01-s02-document-upload') return [
    { locator: page.getByRole('dialog'), name: 'Форма загрузки документа' },
    { locator: page.getByText('synthetic-upload.txt', { exact: true }), name: 'Выбранный файл' },
    { locator: page.getByRole('dialog').getByRole('textbox').first(), name: 'Название документа' },
  ];
  if (scene.shotId === 'm01-s03-upload-completion') {
    const documentRow = page.getByRole('button', { name: 'Synthetic safety instruction', exact: true }).locator('xpath=ancestor::div[contains(@class,"border-b")][1]');
    return [
      { locator: documentRow.getByRole('button', { name: 'Synthetic safety instruction', exact: true }), name: 'Synthetic safety instruction' },
      { locator: documentRow.getByText(/synthetic-upload\.txt\s*·\s*25 B/).first(), name: 'synthetic-upload.txt · 25 B' },
      { locator: documentRow.getByText(/25 B/).first(), name: 'Размер файла 25 B' },
      { locator: documentRow.getByText('Готов', { exact: true }), name: 'Состояние индексации' },
    ];
  }
  if (scene.shotId === 'm01-s04-source-review') return [
    { locator: page.getByText('Вопросы к источнику', { exact: true }).first(), name: 'Вопросы к источнику' },
    { locator: page.getByText('Оригинальный текст', { exact: true }).first(), name: 'Оригинальный текст' },
    { locator: page.getByText('Рабочая редакция', { exact: true }).first(), name: 'Рабочая редакция' },
    { locator: page.locator('pre').filter({ hasText: /^До 45 МРП применяется порядок А\.$/ }), name: 'Оригинальный текст' },
    { locator: page.locator('pre').filter({ hasText: /^До 45 МРП включительно применяется порядок А\.$/ }), name: 'Рабочая редакция' },
  ];
  if (scene.shotId === 'm01-s05-source-history') return [
    { locator: page.getByText('Журнал правок', { exact: true }).first(), name: 'Журнал правок' },
    { locator: page.getByText('Оригинальный текст', { exact: true }).first(), name: 'Оригинальный текст' },
    { locator: page.getByText('Рабочая редакция', { exact: true }).first(), name: 'Рабочая редакция' },
    { locator: page.locator('pre').filter({ hasText: /^До 45 МРП применяется порядок А\.$/ }), name: 'Оригинальный текст' },
    { locator: page.locator('pre').filter({ hasText: /^До 45 МРП включительно применяется порядок А\.$/ }), name: 'Рабочая редакция' },
  ];
  if (scene.shotId === 'm02-s01-document-selection') return [
    { locator: page.getByRole('searchbox', { name: 'Поиск по документам' }), name: 'Поиск по документам' },
    { locator: page.getByText('Synthetic safety instruction', { exact: true }).first(), name: 'Synthetic safety instruction' },
    { locator: page.getByRole('region', { name: 'Выбранные документы' }), name: 'Выбранные документы' },
  ];
  if (scene.shotId === 'm02-s02-generation-settings') return [
    { locator: page.getByText('Прогресс генерации', { exact: true }).first(), name: 'Прогресс генерации' },
    { locator: page.getByText('Выполняется', { exact: true }).first(), name: 'Выполняется' },
  ];
  if (scene.shotId === 'm02-s03-job-state') return [
    { locator: page.getByText('Synthetic workplace safety', { exact: true }).first(), name: 'Synthetic workplace safety' },
    { locator: page.getByText('Safe work', { exact: true }).first(), name: 'Safe work' },
    { locator: page.getByText('Prepare safely', { exact: true }).first(), name: 'Prepare safely' },
  ];
  if (scene.shotId === 'm02-s04-saved-job-link') return [
    { locator: page.getByText('Задания генерации', { exact: true }).first(), name: 'Задания генерации' },
    { locator: page.getByRole('button', { name: /Новый учебный курс.*заявка job-synt/ }), name: 'заявка job-synt' },
    { locator: page.getByRole('heading', { name: 'Детали задачи', exact: true }).first(), name: 'Детали задачи' },
    { locator: page.getByRole('link', { name: 'Открыть задание генерации', exact: true }), name: 'Открыть задание генерации' },
  ];
  if (scene.shotId === 'm03-s01-editor-lesson-select') return [
    { locator: page.getByText('Safe work', { exact: true }).first(), name: 'Safe work' },
    { locator: page.getByText('Prepare safely', { exact: true }).first(), name: 'Prepare safely' },
    { locator: page.getByRole('textbox', { name: 'Содержание урока' }), name: 'Содержание урока' },
  ];
  if (scene.shotId === 'm03-s02-illustration-source-link') return [
    { locator: page.getByRole('textbox', { name: 'Содержание урока' }), name: 'Содержание урока' },
    { locator: page.getByRole('button', { name: 'Открыть как обучающийся', exact: true }), name: 'Открыть как обучающийся' },
  ];
  if (scene.shotId === 'm03-s03-preview-lesson') return [
    { locator: page.locator('article').last(), name: 'Область предпросмотра' },
    { locator: page.getByRole('heading', { name: 'Prepare safely', exact: true }).last(), name: 'Предпросмотр Prepare safely' },
    { locator: page.getByText('Read the safety instructions before starting.', { exact: true }).first(), name: 'Текст урока' },
    { locator: page.getByRole('heading', { name: 'Before work', exact: true }).first(), name: 'Заголовок Before work' },
  ];
  if (scene.shotId === 'm03-s04-save-reopen-lesson') return [
    { locator: page.getByRole('button', { name: 'Сохранить', exact: true }), name: 'Сохранить' },
    { locator: page.getByText('Safe work', { exact: true }).first(), name: 'Safe work' },
    { locator: page.getByRole('button', { name: 'Prepare safely', exact: true }).first(), name: 'Prepare safely' },
    { locator: page.getByText('Синтетическая проверка читаемости.', { exact: true }).first(), name: 'Сохранённая правка' },
  ];
  if (scene.shotId === 'm04-s01-open-test') return [
    { locator: page.getByText('Тесты и вопросы', { exact: true }).first(), name: 'Тесты и вопросы' },
    { locator: page.getByText('Safety knowledge check', { exact: true }).first(), name: 'Safety knowledge check' },
    { locator: page.getByText('Вопросы', { exact: true }).first(), name: 'Вопросы' },
  ];
  if (scene.shotId === 'm04-s02-learner-wording') return [
    { locator: page.getByText('Текст вопроса', { exact: true }).first(), name: 'Текст вопроса' },
    { locator: page.getByText('Варианты ответа', { exact: true }).first(), name: 'Варианты ответа' },
    { locator: page.getByText('Пояснение после ответа', { exact: true }).first(), name: 'Пояснение после ответа' },
  ];
  if (scene.shotId === 'm04-s03-preserve-good-parts') return [
    { locator: page.getByText('Вопросы', { exact: true }).first(), name: 'Вопросы' },
    { locator: page.getByText('Что нужно сделать с повреждённым оборудованием?', { exact: true }).first(), name: 'Сохранённый текст вопроса' },
    { locator: page.getByRole('button', { name: 'Редактировать', exact: true }).first(), name: 'Редактировать' },
  ];
  if (scene.shotId === 'm04-s04-reopen-saved-test') return [
    { locator: page.getByRole('textbox', { name: 'Текст вопроса' }), name: 'Текст вопроса' },
  ];
  if (scene.shotId === 'm05-s01-review-before-approval') return [
    { locator: page.locator('[data-publication-checks] summary'), name: 'Проверка и публикация — подробности' },
    { locator: page.getByRole('button', { name: 'Открыть замечания и источники' }), name: 'Открыть замечания и источники' },
  ];
  if (scene.shotId === 'm05-s02-approve-course') return [
    { locator: page.getByRole('button', { name: 'Опубликовать', exact: true }), name: 'Опубликовать' },
    { locator: page.getByRole('group', { name: 'Редактировать курс' }).getByText('Черновик', { exact: true }).first(), name: 'Черновик' },
  ];
  if (scene.shotId === 'm05-s03-publish-separately') return [
    { locator: page.getByRole('group', { name: 'Редактировать курс' }).getByText('Опубликован', { exact: true }).first(), name: 'Статус опубликован' },
  ];
  if (scene.shotId === 'm05-s04-published-state') {
    const card = page.getByRole('region', { name: 'Открыть курс' });
    return [
      { locator: card.getByText('Synthetic workplace safety', { exact: true }).first(), name: 'Synthetic workplace safety' },
      { locator: card.getByText(/Опубликован/).first(), name: 'Статус опубликован' },
      { locator: card.getByRole('link', { name: 'Назначить сотрудникам' }), name: 'Назначить сотрудникам' },
    ];
  }
  if (scene.shotId === 'm06-s01-staff-list') return [
    { locator: page.getByRole('tab', { name: 'Список' }), name: 'Список' },
    { locator: page.getByText('Синтетический сотрудник', { exact: true }).first(), name: 'Синтетический сотрудник' },
  ];
  if (scene.shotId === 'm06-s02-structure-add-unit') return [
    { locator: page.getByRole('dialog'), name: 'Форма подразделения' },
    { locator: page.getByText(/Тип подразделения/).first(), name: 'Тип подразделения' },
  ];
  if (scene.shotId === 'm06-s03-import-preview') return [
    { locator: page.getByRole('heading', { level: 1, name: 'Импорт сотрудников' }), name: 'Импорт сотрудников' },
    { locator: page.getByText(/Сопоставление/).first(), name: 'Сопоставление' },
    { locator: page.getByText(/Предложение/).first(), name: 'Предложение' },
    { locator: page.getByText(/Конфликты/).first(), name: 'Конфликты' },
    { locator: page.getByText(/SYN-001/).first(), name: 'Сотрудник SYN-001' },
    { locator: page.getByText('Учебное подразделение', { exact: true }).first(), name: 'Учебное подразделение' },
  ];
  if (scene.shotId === 'm06-s04-import-apply-verify') return [
    { locator: page.getByRole('tab', { name: 'Список' }), name: 'Список' },
    { locator: page.getByRole('button', { name: /Синтетический сотрудник.*Учебное подразделение/ }), name: 'Синтетический сотрудник · Учебное подразделение' },
  ];
  if (scene.shotId === 'm07-s01-course-assign-entry') return [
    { locator: page.getByText('Назначить', { exact: true }).first(), name: 'Назначить' },
    { locator: page.getByText('Текущие назначения', { exact: true }).first(), name: 'Текущие назначения' },
    { locator: page.getByText('Курс: Synthetic workplace safety', { exact: true }).first(), name: 'Курс: Synthetic workplace safety' },
    { locator: page.getByRole('heading', { name: 'Обучающиеся', exact: true }), name: 'Обучающиеся' },
  ];
  if (scene.shotId === 'm07-s02-mode-assign') return [
    { locator: page.getByText('Назначить', { exact: true }).first(), name: 'Назначить' },
    { locator: page.getByText('Курс: Synthetic workplace safety', { exact: true }).first(), name: 'Курс: Synthetic workplace safety' },
    { locator: page.getByRole('heading', { name: 'Обучающиеся', exact: true }), name: 'Обучающиеся' },
  ];
  if (scene.shotId === 'm07-s03-recipient-delivery-pin') return [
    { locator: page.getByRole('checkbox', { name: 'Synthetic Learner' }), name: 'Synthetic Learner' },
    { locator: page.getByRole('radio', { name: /^Персональная ссылка и PIN/ }), name: 'Персональная ссылка и PIN' },
    { locator: page.getByRole('radio', { name: /^Email/ }), name: 'Email' },
  ];
  if (scene.shotId === 'm07-s04-confirm-current-record') return [
    { locator: page.getByText('Synthetic Learner', { exact: true }).first(), name: 'Synthetic Learner' },
    { locator: page.getByRole('button', { name: 'Получить ссылку', exact: true }).first(), name: 'Получить ссылку' },
  ];
  if (scene.shotId === 'm08-s01-person-search') return [
    { locator: page.getByRole('textbox', { name: 'Поиск' }), name: 'Поиск' },
    { locator: page.getByRole('button', { name: /Синтетический сотрудник/ }).first(), name: 'Синтетический сотрудник' },
    { locator: page.getByText('Фильтры', { exact: true }).first(), name: 'Фильтры' },
  ];
  if (scene.shotId === 'm08-s02-training-completion') return [
    { locator: page.getByRole('heading', { name: 'Синтетический сотрудник', exact: true }), name: 'Синтетический сотрудник' },
    { locator: page.getByText('Завершён', { exact: true }).first(), name: 'Завершён' },
    { locator: page.getByText('Подписанный экземпляр принят', { exact: true }).first(), name: 'Подписанный экземпляр принят' },
    { locator: page.getByText('SYN-CERT-001', { exact: true }).first(), name: 'Сертификат SYN-CERT-001' },
  ];
  if (scene.shotId === 'm08-s03-signed-copy-state') return [
    { locator: page.getByRole('textbox', { name: 'Поиск' }), name: 'Поиск' },
    { locator: page.getByRole('checkbox', { name: 'Включить историю назначений' }), name: 'Включить историю назначений' },
    { locator: page.getByRole('button', { name: /Синтетический сотрудник.*Завершён/ }).first(), name: 'Синтетический сотрудник · Завершён' },
    { locator: page.getByRole('button', { name: /Синтетический сотрудник.*0%/ }).first(), name: 'Историческая запись · 0%' },
    { locator: page.getByRole('region', { name: 'Журнал обучения' }).getByText('Подписанный экземпляр принят', { exact: true }).first(), name: 'Подписанный экземпляр принят' },
  ];
  if (scene.shotId === 'm08-s04-csv-export-scope') return [
    { locator: page.getByRole('button', { name: /CSV/ }).first(), name: 'CSV-экспорт' },
  ];
  return [];
};

const manifestShotIds = new Set<string>();

async function readManifest() {
  const manifestText = await readFile(manifestPath, 'utf8');
  return { manifestText, manifestSha256: createHash('sha256').update(manifestText).digest('hex') };
}

async function writePartialReceipt(missingShotIds: string[], reason: string) {
  const { manifestSha256 } = await readManifest().catch(() => ({ manifestSha256: null }));
  await writeFile(partialReceiptPath, JSON.stringify({
    schema_version: 1,
    status: 'HOLD',
    run_id: runId,
    source_baseline: sourceBaseline,
    source_sha256: sourceSha256,
    manifest_sha256: manifestSha256,
    missing_shot_ids: missingShotIds,
    reason,
  }, null, 2));
}

test.describe('methodologist guide: authentic synthetic captures', () => {
  test.beforeAll(async () => {
    const { manifestText } = await readManifest();
    const manifest = JSON.parse(manifestText) as { chapters: Array<{ segments: Array<{ shot_id: string }> }> };
    for (const chapter of manifest.chapters) for (const segment of chapter.segments) manifestShotIds.add(segment.shot_id);
    await mkdir(outDir, { recursive: true });
  });

  for (const scene of scenes) {
    test(`${scene.shotId} @1440`, async ({ page, workspace }) => {
      scene.prepare?.(workspace);
      await gotoAndSettle(page, resolveRoute(scene.route));
      await scene.act(page, workspace);
      const verifiedControls = await verifyControls(page, controlAssertions(page, scene));
      const viewport = page.viewportSize();
      if (!viewport) throw new Error('Guide capture requires an explicit viewport');
      const rawPath = join(outDir, `${scene.shotId}.raw.png`);
      const sha256 = await saveShot(page, scene.shotId, rawPath);
      const { manifestSha256 } = await readManifest();
      await writeFile(join(outDir, `${scene.shotId}.capture.json`), JSON.stringify({
        shot_id: scene.shotId,
        route: scene.route,
        run_id: runId,
        source_baseline: sourceBaseline,
        source_sha256: sourceSha256,
        png_sha256: sha256,
        raw_png_sha256: sha256,
        viewport,
        visible_controls_verified: true,
        verified_controls: verifiedControls,
        synthetic: true,
        manifest_sha256: manifestSha256,
      } satisfies CaptureReceipt, null, 2));
    });
  }

  test('guide captures: 390px help/navigation/outflow sample', async ({ page, workspace }) => {
    installMethodologistReads(workspace, 'dashboard');
    await page.setViewportSize({ width: 390, height: 844 });
    await gotoAndSettle(page, '/dashboard');
    await expect(page.getByText('Задания генерации', { exact: true }).first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    const mobilePath = join(outDir, 'm01-s01-dashboard-tasks.mobile.png');
    await page.screenshot({ path: mobilePath, fullPage: true, animations: 'disabled' });
  });
});

test.afterAll(async () => {
  const { manifestText, manifestSha256 } = await readManifest();
  const manifest = JSON.parse(manifestText) as { chapters: Array<{ segments: Array<{ shot_id: string; route: string }> }> };
  const expected = manifest.chapters.flatMap((chapter) => chapter.segments.map((segment) => segment.shot_id));
  const entries: CaptureReceipt[] = [];
  const missing: string[] = [];
  for (const shotId of expected) {
    try {
      const capture = JSON.parse(await readFile(join(outDir, `${shotId}.capture.json`), 'utf8')) as CaptureReceipt;
      const shot = await readFile(join(outDir, `${shotId}.png`));
      const raw = await readFile(join(outDir, `${shotId}.raw.png`));
      expect(capture.shot_id).toBe(shotId);
      expect(capture.run_id).toBe(runId);
      expect(capture.synthetic).toBe(true);
      expect(capture.visible_controls_verified).toBe(true);
      expect(capture.source_baseline).toBe(sourceBaseline);
      expect(capture.source_sha256).toBe(sourceSha256);
      expect(capture.manifest_sha256).toBe(manifestSha256);
      expect(capture.viewport.width).toBeGreaterThan(0);
      expect(capture.viewport.height).toBeGreaterThan(0);
      expect(capture.verified_controls.length).toBeGreaterThan(0);
      expect(createHash('sha256').update(shot).digest('hex')).toBe(capture.png_sha256);
      expect(createHash('sha256').update(raw).digest('hex')).toBe(capture.raw_png_sha256);
      expect(shot.equals(raw)).toBe(true);
      entries.push(capture);
    } catch (error) {
      missing.push(shotId);
    }
  }
  if (missing.length > 0) {
    await writePartialReceipt(missing, 'Missing or invalid current-run capture receipts; capture set remains HOLD.');
    throw new Error(`Guide capture set is HOLD: missing/invalid ${missing.length} current-manifest shot(s): ${missing.join(', ')}`);
  }
  await writeFile(captureManifestPath, JSON.stringify({
    schema_version: 1,
    status: 'PASS',
    run_id: runId,
    source_baseline: sourceBaseline,
    source_sha256: sourceSha256,
    manifest_sha256: manifestSha256,
    captures: entries,
  }, null, 2));
});
