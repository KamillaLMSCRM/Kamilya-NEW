import { expect, test as base, type BrowserContext } from '@playwright/test';

export const appOrigin = process.env.KAMILYA_WORKSPACE_TEST_ORIGIN || 'http://127.0.0.1:3024';
if (!['http://127.0.0.1:3024', 'http://127.0.0.1:3026', 'http://127.0.0.1:3027'].includes(appOrigin)) {
  throw new Error('Synthetic workspace tests require an explicitly allowed loopback origin.');
}
const uuid = (suffix: number) => `71000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`;
export const ids = {
  tenant: uuid(1), learner: uuid(2), author: uuid(3), course: uuid(4), module: uuid(5),
  lesson: uuid(6), secondLesson: uuid(7), enrollment: uuid(8), quiz: uuid(9),
  question: uuid(10), safeChoice: uuid(11), unsafeChoice: uuid(12), attempt: uuid(13),
  evidence: uuid(14), document: uuid(15), request: uuid(16), revision: uuid(17),
  reviewAttempt: uuid(18), department: uuid(19), existingLearner: uuid(20),
};
export const timestamp = '2026-11-01T10:00:00Z';
export const course = {
  id: ids.course, tenant_id: ids.tenant, title: 'Synthetic workplace safety',
  description: 'Synthetic browser acceptance material. No customer data.',
  status: 'published', delivery_type: 'native', ai_generated: false,
  review_status: 'pending', requires_approval: true, source_instruction_id: null,
  thumbnail_url: null, created_at: timestamp, updated_at: timestamp,
};
export const lessons = [
  { id: ids.lesson, module_id: ids.module, title: 'Prepare safely', content_type: 'text',
    content: '# Prepare safely\n\nRead the safety instructions before starting.\n\n## Before work\n\n- Inspect equipment.\n- Report damage.', order_index: 0 },
  { id: ids.secondLesson, module_id: ids.module, title: 'Report a hazard', content_type: 'text',
    content: '# Report a hazard\n\nStop work and notify the supervisor.\n\n> Do not restart damaged equipment.', order_index: 1 },
];
export const structure = { modules: [{ id: ids.module, course_id: ids.course,
  title: 'Safe work', order_index: 0, lessons }] };
export const assignment = {
  enrollment_id: ids.enrollment, course_id: ids.course, title: course.title,
  description: course.description, status: 'published', enrollment_status: 'in_progress',
  delivery_type: 'native', progress_percent: 0, total_lessons: 2, completed_lessons: 0,
  enrolled_at: timestamp, thumbnail_url: null, assignment_due_at: null,
  assignment_source: 'manual', can_resume: true,
  resume_href: `/courses/${ids.course}?lessonId=${ids.lesson}`,
};
export const quiz = {
  id: ids.quiz, lesson_id: ids.lesson, title: 'Safety knowledge check', pass_score: 80,
  time_limit: null, attempt_limit: 2, deferral_days: 30,
  questions: [{ id: ids.question, text: 'What should you do with damaged equipment?',
    type: 'single_choice', points: 1, explanation: null, order_index: 0,
    choices: [
      { id: ids.safeChoice, text: 'Stop and report the damage', order_index: 0 },
      { id: ids.unsafeChoice, text: 'Continue using it', order_index: 1 },
    ] }],
};
export const quizAttempt = {
  id: ids.attempt, quiz_id: ids.quiz, user_id: ids.learner, score_percent: 100,
  total_points: 1, earned_points: 1, passed: true, started_at: timestamp,
  completed_at: timestamp, time_spent_seconds: 5,
};
export const quizResult = {
  attempt: quizAttempt, passed: true, message: 'Synthetic knowledge check passed.',
  training_evidence_event_id: ids.evidence,
};
export const evidenceEvent = {
  id: ids.evidence, enrollment_id: ids.enrollment, content_release_id: ids.revision,
  procedure_type: 'knowledge_check', record_type: 'quiz_attempt', related_event_id: null,
  occurred_at: timestamp, created_at: timestamp, confirmation_status: 'not_required',
  procedure_title: quiz.title, release_version: 3, release_sha256: 'a'.repeat(64),
  confirmation_statement: null, confirmation_object_version: null,
};
export const sourceDocument = {
  id: ids.document, source_family_id: ids.document, title: 'Synthetic safety instruction',
  filename: 'synthetic-safety-instruction.pdf', content_type: 'application/pdf', size: 2048,
  description: 'The index is partial; the original remains the inspection source.',
  category: 'general', index: { status: 'partial', error_code: null,
    message: 'Two fragments indexed; one still requires inspection.', chunks_total: 3,
    chunks_indexed: 2, indexed_at: timestamp, revision: 7 },
  version: 3, is_latest: true, lifecycle_status: 'active', deletion_error_code: null,
  deletion_error_message: null, deletion_job_id: null, created_by: 'Synthetic author',
  created_at: timestamp, updated_at: timestamp,
  // Deliberately unavailable: inspection must show an em dash, not invented zero usage.
  usages_summary: null,
};
export const audience = [
  { id: ids.learner, first_name: 'Synthetic', last_name: 'Learner', role: 'student',
    email: 'learner@example.invalid', is_active: true, has_login_access: true,
    personnel_number: 'SYN-001', position_name: 'Operator' },
  { id: ids.existingLearner, first_name: 'Existing', last_name: 'Graduate', role: 'student',
    email: 'graduate@example.invalid', is_active: true, has_login_access: true,
    personnel_number: 'SYN-002', position_name: 'Operator' },
];
export const existingEnrollment = {
  id: uuid(21), course_id: ids.course, user_id: ids.existingLearner, status: 'completed',
  source: 'manual', enrolled_at: timestamp, completed_at: timestamp, progress_percent: 100,
};
export const newEnrollment = {
  id: ids.enrollment, course_id: ids.course, user_id: ids.learner, status: 'enrolled',
  source: 'manual', enrolled_at: timestamp, completed_at: null, progress_percent: 0,
};
export const snapshotHash = 'b'.repeat(64);
export const reviewSummary = {
  request_id: ids.request, revision_id: ids.revision, outcome: 'pending',
  delivery_mode: 'email', reviewer_ids: [ids.author], all_required_approved: false,
};
export const reviewAttempt = {
  attempt_id: ids.reviewAttempt, revision_id: ids.revision, snapshot_sha256: snapshotHash,
  activity_state: 'completed', lesson_position: 0, next_sequence: 4,
  snapshot: { schema_version: 1, release_version: 3,
    course: { id: ids.course, title: 'Frozen safety version' },
    modules: [{ id: ids.module, title: 'Frozen module', order_index: 0,
      lessons: [{ ...lessons[0], content: 'This is the frozen version three, not a current draft.', quizzes: [] }] }] },
};

export const trainingRows = Array.from({ length: 102 }, (_, index) => ({
  user_id: uuid(1000 + index), full_name: `Synthetic employee ${String(index + 1).padStart(3, '0')}`,
  email: `employee-${index + 1}@example.invalid`, personnel_number: `SYN-${index + 1}`,
  department_id: ids.department, department_name: 'Synthetic operations', position_id: null,
  position_name: 'Operator', course_id: ids.course, course_title: course.title,
  delivery_type: 'native', enrollment_status: index === 101 ? 'superseded' : 'in_progress',
  previous_enrollment_id: null, reassignment_reason: null, enrollment_source: 'manual',
  enrolled_at: timestamp, completed_at: null, cycle_id: null, cycle_type: null,
  cycle_scheduled_for: null, cycle_due_at: null, deadline_status: 'not_applicable',
  assignment_due_at: null, deadline_state: 'none', enrollment_id: uuid(2000 + index),
  latest_evidence_event_id: null, evidence_procedure_type: null,
  evidence_confirmation_status: 'not_required', evidence_signed_copy_status: 'awaiting_return',
  evidence_state: 'forming', evidence_events: [], computed_status: 'in_progress',
  progress_percent: 50, best_score: null, quiz_attempts_count: 0,
  certificate_id: null, certificate_number: null, certificate_issued_at: null,
  certificate_expires_at: null, certificate_status: 'none', kiosk_last_seen_at: null,
}));

type Reply = { json?: unknown; status?: number; body?: string; contentType?: string };
type ApiCall = { method: string; path: string; url: URL; body: unknown };
type Handler = (call: ApiCall) => Reply | Promise<Reply>;

/** Every API call is local synthetic data. Unknown reads/writes receive 501, never passthrough. */
export class SyntheticWorkspace {
  role: 'student' | 'methodologist' | 'admin' | 'superadmin' = 'student';
  assignedRoles?: Array<'student' | 'methodologist' | 'admin' | 'superadmin'>;
  presentation: { tenantName?: string; fullName?: string; impersonatedBy?: string } = {};
  expectsSession = true;
  readonly calls: ApiCall[] = [];
  readonly unexpectedApi: string[] = [];
  readonly unexpectedMutations: string[] = [];
  readonly externalRequests: string[] = [];
  readonly pageErrors: string[] = [];
  private readonly reads = new Map<string, Handler>();
  private readonly commands = new Map<string, Handler>();

  constructor(private readonly context: BrowserContext, private readonly language: 'ru' | 'kk' | 'en' = 'en') {}

  get(path: string, body: unknown) { this.onGet(path, () => ({ json: body })); }
  onGet(path: string, handler: Handler) { this.reads.set(path, handler); }
  // One exact command is armed immediately before its explicit UI action.
  command(method: 'POST' | 'PATCH' | 'PUT', path: string, handler: Handler) {
    this.commands.set(`${method} ${path}`, handler);
  }
  matching(method: string, path: string) {
    return this.calls.filter((call) => call.method === method && call.path === path);
  }

  async install() {
    await this.context.addInitScript(({ lang, origin }) => {
      if (window.location.origin !== origin) return;
      localStorage.setItem('kamilya-language', JSON.stringify({ state: { lang }, version: 0 }));
    }, { lang: this.language, origin: appOrigin });
    this.context.on('page', (page) => page.on('pageerror', (error) => this.pageErrors.push(error.message)));
    for (const page of this.context.pages()) {
      page.on('pageerror', (error) => this.pageErrors.push(error.message));
    }
    await this.context.route('**/*', async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const method = request.method();
      const apiIndex = url.pathname.indexOf('/v1/');
      if (apiIndex !== -1) {
        const path = url.pathname.slice(apiIndex);
        const cors = {
          'access-control-allow-origin': appOrigin,
          'access-control-allow-credentials': 'true',
          'access-control-allow-methods': 'GET, HEAD, POST, PATCH, PUT, DELETE, OPTIONS',
          'access-control-allow-headers': 'authorization, content-type, accept, x-request-id',
        };
        if (method === 'OPTIONS') {
          await route.fulfill({ status: 204, headers: cors });
          return;
        }
        let body: unknown = null;
        try { body = request.postDataJSON(); } catch { body = request.postData(); }
        const call: ApiCall = { method, path, url, body };
        this.calls.push(call);
        const actor = {
          user_id: this.role === 'student' ? ids.learner : ids.author, tenant_id: ids.tenant,
          tenant: { id: ids.tenant, name: this.presentation.tenantName ?? 'Synthetic workspace QA', slug: 'synthetic-workspace', is_demo: false },
          telegram_id: '0', role: this.role, roles: this.assignedRoles ?? [this.role],
          first_name: 'Synthetic', last_name: this.role === 'student' ? 'Learner' : 'Author',
          full_name: this.presentation.fullName ?? (this.role === 'student' ? 'Synthetic Learner' : 'Synthetic Author'),
          impersonated_by: this.presentation.impersonatedBy,
          email: this.role === 'student' ? 'learner@example.invalid' : 'author@example.invalid',
        };
        let reply: Reply;
        if (method === 'POST' && path === '/v1/auth/refresh') {
          reply = { json: { access_token: `synthetic-workspace-token-not-a-real-jwt-${this.matching('POST', '/v1/auth/refresh').length}`, user: actor } };
        } else if (method === 'GET' && path === '/v1/users/me') {
          reply = { json: actor };
        } else {
          const key = `${method} ${path}`;
          const handler = method === 'GET' ? this.reads.get(path) : this.commands.get(key);
          if (method !== 'GET') {
            if (handler) this.commands.delete(key);
            else this.unexpectedMutations.push(key);
          }
          if (handler) reply = await handler(call);
          else {
            this.unexpectedApi.push(key);
            reply = { status: 501, json: { detail: `Unlisted synthetic API contract: ${key}` } };
          }
        }
        await route.fulfill({ status: reply.status ?? 200, headers: cors,
          ...(reply.body !== undefined
            ? { body: reply.body, contentType: reply.contentType ?? 'text/plain; charset=utf-8' }
            : { json: reply.json }) });
        return;
      }
      if (url.origin === appOrigin) {
        if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) this.unexpectedMutations.push(`${method} ${url.pathname}`);
        await route.continue();
      } else {
        if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) this.unexpectedMutations.push(`${method} ${url.origin}${url.pathname}`);
        this.externalRequests.push(`${method} ${url.origin}${url.pathname}`);
        await route.abort('blockedbyclient');
      }
    });
  }

  learner() {
    this.get(`/v1/courses/${ids.course}`, course);
    this.get(`/v1/courses/${ids.course}/structure`, structure);
    this.get(`/v1/courses/${ids.course}/access-window`, null);
    this.get(`/v1/progress/courses/${ids.course}/completed-ids`, { completed_lesson_ids: [] });
    this.get('/v1/student/dashboard', { user_id: ids.learner, full_name: 'Synthetic Learner',
      enrolled_courses: [assignment], total_courses: 1, completed_courses: 0,
      total_progress_percent: 0, certificates_count: 0 });
    this.get(`/v1/quizzes/by-lesson/${ids.lesson}`, quiz);
    this.onGet(`/v1/quizzes/by-lesson/${ids.secondLesson}`, () => ({ status: 404, json: { detail: 'No quiz for this lesson' } }));
    this.get(`/v1/quizzes/${ids.quiz}`, quiz);
    this.get(`/v1/quizzes/${ids.quiz}/attempts`, []);
    this.get('/v1/learner/assistant/messages', []);
    this.get(`/v1/training-evidence/events/mine/${ids.evidence}`, evidenceEvent);
  }

  author() {
    this.role = 'methodologist';
    this.get(`/v1/courses/${ids.course}`, { ...course, status: 'draft', ai_generated: true });
    this.get(`/v1/courses/${ids.course}/structure`, structure);
    for (const lesson of lessons) this.get(`/v1/lessons/${lesson.id}`, lesson);
    this.get(`/v1/courses/${ids.course}/approval-policy`, {
      course_id: ids.course, requires_approval: true, review_enabled: true,
    });
    const authorQuiz = { ...quiz, questions: quiz.questions.map((question) => ({ ...question, type: 'MCQ', choices: question.choices.map((choice, index) => ({ ...choice, is_correct: index === 0 })) })) };
    this.get('/v1/quizzes/grouped', { courses: [{ ...course, status: 'draft', modules: [{ ...structure.modules[0], lessons: [{ ...lessons[0], quiz: authorQuiz }] }] }], orphans: [] });
  }

  documents() {
    this.role = 'methodologist';
    this.get('/v1/documents/catalog', { items: [sourceDocument],
      page: { next_cursor: null, has_more: false, limit: 25 } });
    this.get('/v1/youtube/limits', { enabled: false });
    this.get('/v1/admin/source-actuality', { items: [] });
  }

  assignments() {
    this.role = 'methodologist';
    this.get('/v1/courses', [course]);
    this.get('/v1/users', { users: audience, total: audience.length });
    this.get('/v1/learning-cycles', []);
    this.get('/v1/learning-cycles/occurrences', []);
    this.get(`/v1/courses/${ids.course}/enrollments`, [existingEnrollment]);
  }

  trainingLog() {
    this.role = 'methodologist';
    this.get('/v1/courses', [course]);
    this.get('/v1/admin/learning-actions', {
      summary: { training_log: null, training_issue_count: 0, training_issue_counts: {},
        training_items_truncated: false, weak_question_count: 0, action_count: 0,
        actions_truncated: false, open_action_count: 0, overdue_action_count: 0 },
      training_items: [], weak_questions: [], actions: [],
    });
    const rowsFor = (url: URL) => trainingRows.slice(0, url.searchParams.get('history') === 'true' ? 102 : 101);
    this.onGet('/v1/admin/training-log/summary', ({ url }) => ({ json: {
      total: rowsFor(url).length, assigned: 0, in_progress: rowsFor(url).length, completed: 0, overdue: 0,
    } }));
    this.onGet('/v1/admin/training-log', ({ url }) => {
      const rows = rowsFor(url);
      if (url.searchParams.get('format') === 'csv') return {
        contentType: 'text/csv; charset=utf-8',
        body: '\uFEFFEmployee,Course,Status\r\n' + rows.map((row) => `${row.full_name},${row.course_title},${row.enrollment_status}`).join('\r\n') + '\r\n',
      };
      const limit = Number(url.searchParams.get('limit') ?? 100);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      return { json: { items: rows.slice(offset, offset + limit), total: rows.length,
        limit, offset, reporting_scope: 'restricted' } };
    });
  }

  assertIsolated() {
    expect(this.unexpectedMutations, 'Only explicitly armed synthetic commands may mutate').toEqual([]);
    expect(this.unexpectedApi, 'Every /v1/ endpoint needs an explicit synthetic fixture').toEqual([]);
    expect(this.externalRequests, 'Only the dedicated loopback app may receive passthrough traffic').toEqual([]);
    expect(this.pageErrors, 'Production pages must not crash').toEqual([]);
    expect(this.commands.size, 'Every armed command must be consumed exactly once').toBe(0);
    if (this.expectsSession) {
      expect(this.matching('POST', '/v1/auth/refresh').length, 'Session restoration is intercepted, never real auth').toBeGreaterThan(0);
    } else {
      expect(this.matching('POST', '/v1/auth/refresh').length, 'Public screens must not attempt a tenant session').toBe(0);
    }
  }
}

export const test = base.extend<{ workspace: SyntheticWorkspace }>({
  workspace: async ({ context }, runTest) => {
    const workspace = new SyntheticWorkspace(context);
    await workspace.install();
    await runTest(workspace);
    workspace.assertIsolated();
  },
});
