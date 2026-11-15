import { expect, test } from '@playwright/test';
import { appOrigin, ids, SyntheticWorkspace } from './learning-workspace-ux-fixtures';

if (!process.env.PLAYWRIGHT_SKIP_WEBSERVER) throw new Error('Use an isolated loopback server with all APIs intercepted.');
test.use({ baseURL: appOrigin, ...(process.env.KAMILYA_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.KAMILYA_BROWSER_EXECUTABLE } } : {}) });

test('mobile learner restores and saves an existing attempt', async ({ page, context }) => {
  const workspace = new SyntheticWorkspace(context, 'en');
  workspace.role = 'student';
  const assignment = { id:ids.enrollment, check_id:ids.quiz, title:'Synthetic safety check', revision:1, due_at:null, status:'in_progress', attempt_limit:2, attempts_count:1, score_percent:null, passed:false, attempts:[{ id:ids.attempt, number:1, status:'started' }] };
  const attempt = { id:ids.attempt, assignment_id:ids.enrollment, number:1, status:'started', started_at:'2026-11-01T10:00:00Z', deadline_at:null, completed_at:null, score_percent:null, passed:null, earned_points:null, total_points:null, answers:[{question_id:ids.question,selected_choice_ids:[ids.safeChoice]}], snapshot:{title:'Synthetic safety check',instructions:'Choose an answer',questions:[{id:ids.question,text:'What should you do?',type:'MCQ',points:1,choices:[{id:ids.safeChoice,text:'Stop'},{id:ids.unsafeChoice,text:'Continue'}]}]} };
  workspace.get(`/v1/knowledge-checks/assignments/${ids.enrollment}`, assignment);
  workspace.get(`/v1/knowledge-checks/attempts/${ids.attempt}`, attempt);
  workspace.command('PUT', `/v1/knowledge-checks/attempts/${ids.attempt}/answers`, ({ body }) => ({ json:{...attempt, ...body as object} }));
  await workspace.install();
  await page.setViewportSize({width:390,height:844});
  await page.goto(`/my-knowledge-checks/${ids.enrollment}`);
  await expect.poll(() => workspace.matching('POST', '/v1/auth/refresh').length, { message:'Synthetic session restoration must be intercepted' }).toBeGreaterThan(0);
  await expect(page.getByRole('radio', {name:'Stop'})).toBeChecked();
  await page.getByRole('radio', {name:'Continue'}).check();
  await page.getByRole('button', {name:'Save answers'}).click();
  await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible();
  expect(workspace.matching('PUT', `/v1/knowledge-checks/attempts/${ids.attempt}/answers`)[0].body).toEqual({answers:[{question_id:ids.question,selected_choice_ids:[ids.unsafeChoice]}]});
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  workspace.assertIsolated();
});

const checkId = '72000000-0000-4000-8000-000000000001';
const assignmentId = '72000000-0000-4000-8000-000000000002';
const firstAttemptId = '72000000-0000-4000-8000-000000000003';
const retryId = '72000000-0000-4000-8000-000000000004';
const questionId = '72000000-0000-4000-8000-000000000005';
const correctId = '72000000-0000-4000-8000-000000000006';
const wrongId = '72000000-0000-4000-8000-000000000007';
const startedAt = '2026-11-01T10:00:00Z';
const publicSnapshot = {
  title: 'Safety check', instructions: 'Select one answer', pass_score: 70,
  attempt_limit: 2, time_limit_minutes: null,
  questions: [{ id: questionId, text: 'What should you do?', type: 'MCQ', points: 1,
    choices: [{ id: correctId, text: 'Stop work' }, { id: wrongId, text: 'Continue work' }] }],
};
type SyntheticAnswer = { question_id: string; selected_choice_ids: string[] };
type SyntheticAttempt = {
  id: string; assignment_id: string; number: number; status: string; started_at: string;
  deadline_at: string | null; completed_at: string | null; score_percent: number | null;
  passed: boolean | null; earned_points: number | null; total_points: number | null;
  answers: SyntheticAnswer[]; snapshot: typeof publicSnapshot;
};
const newAttempt = (id: string, number: number): SyntheticAttempt => ({
  id, assignment_id: assignmentId, number, status: 'started', started_at: startedAt,
  deadline_at: null, completed_at: null, score_percent: null, passed: null,
  earned_points: null, total_points: null, answers: [], snapshot: publicSnapshot,
});

for (const width of [390, 1440]) {
  test(`learner completes a failed attempt and retry with retained history at ${width}px`, async ({ page, context }) => {
    const workspace = new SyntheticWorkspace(context, 'en');
    const attempts: SyntheticAttempt[] = [];
    const summary = () => {
      const latest = attempts.at(-1);
      return { id: assignmentId, check_id: checkId, title: publicSnapshot.title, revision: 1,
        due_at: null, status: !latest ? 'assigned' : !latest.completed_at ? 'in_progress' : latest.passed ? 'passed' : 'failed',
        attempt_limit: 2, attempts_count: attempts.length, score_percent: latest?.score_percent ?? null,
        passed: latest?.passed ?? null };
    };
    workspace.onGet('/v1/knowledge-checks/my', () => ({ json: { items: [summary()], has_more: false } }));
    workspace.onGet(`/v1/knowledge-checks/assignments/${assignmentId}`, () => ({ json: { ...summary(), attempts } }));
    workspace.onGet(`/v1/knowledge-checks/attempts/${firstAttemptId}`, () => ({ json: attempts[0] }));
    workspace.onGet(`/v1/knowledge-checks/attempts/${retryId}`, () => ({ json: attempts[1] }));
    await workspace.install();
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/my-knowledge-checks');
    await expect(page.getByText('Safety check', { exact: true })).toBeVisible();
    await page.getByRole('link', { name: 'Open' }).click();

    workspace.command('POST', `/v1/knowledge-checks/assignments/${assignmentId}/start`, ({ body }) => {
      expect(body).toEqual({}); attempts.push(newAttempt(firstAttemptId, 1)); return { json: attempts[0] };
    });
    await page.getByRole('button', { name: 'Start or resume' }).click();
    await page.getByRole('radio', { name: 'Continue work' }).check();
    workspace.command('PUT', `/v1/knowledge-checks/attempts/${firstAttemptId}/answers`, ({ body }) => {
      expect(body).toEqual({ answers: [{ question_id: questionId, selected_choice_ids: [wrongId] }] });
      attempts[0] = { ...attempts[0], answers: (body as { answers: SyntheticAnswer[] }).answers };
      return { json: attempts[0] };
    });
    await page.getByRole('button', { name: 'Save answers' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Saved' })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('radio', { name: 'Continue work' })).toBeChecked();
    workspace.command('POST', `/v1/knowledge-checks/attempts/${firstAttemptId}/submit`, ({ body }) => {
      expect(body).toEqual({ answers: [{ question_id: questionId, selected_choice_ids: [wrongId] }] });
      attempts[0] = { ...attempts[0], status:'submitted', completed_at:startedAt, score_percent:0, passed:false, earned_points:0, total_points:1 };
      return { json: attempts[0] };
    });
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText('Not passed: 0% (0/1)')).toBeVisible();
    await expect(page.getByText('Attempts 1 · Submitted · 0%')).toBeVisible();
    await page.getByRole('button', { name: 'Start or resume' }).click();
    workspace.command('POST', `/v1/knowledge-checks/assignments/${assignmentId}/start`, ({ body }) => {
      expect(body).toEqual({}); attempts.push(newAttempt(retryId, 2)); return { json: attempts[1] };
    });
    await page.getByRole('button', { name: 'Start or resume' }).click();
    await page.getByRole('radio', { name: 'Stop work' }).check();
    workspace.command('POST', `/v1/knowledge-checks/attempts/${retryId}/submit`, ({ body }) => {
      expect(body).toEqual({ answers: [{ question_id: questionId, selected_choice_ids: [correctId] }] });
      attempts[1] = { ...attempts[1], answers: (body as { answers: SyntheticAnswer[] }).answers,
        status:'submitted', completed_at:startedAt, score_percent:100, passed:true, earned_points:1, total_points:1 };
      return { json: attempts[1] };
    });
    page.once('dialog', dialog => dialog.accept());
    await page.getByRole('button', { name: 'Submit' }).click();
    await expect(page.getByText('Passed: 100% (1/1)')).toBeVisible();
    await expect(page.getByText('Attempts 1 · Submitted · 0%')).toBeVisible();
    await expect(page.getByText('Attempts 2 · Submitted · 100%')).toBeVisible();
    await page.reload();
    await expect(page.getByText('Attempts 1 · Submitted · 0%')).toBeVisible();
    await expect(page.getByText('Attempts 2 · Submitted · 100%')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    workspace.assertIsolated();
  });
}

for (const width of [390, 1440]) {
  test(`author creates, assigns and retains revision 1 results after revision 2 at ${width}px`, async ({ page, context }) => {
    const workspace = new SyntheticWorkspace(context, 'en');
    workspace.role = 'methodologist';
    type AuthoredQuestion = { id:string; text:string; type:string; points:number; explanation:string | null;
      choices:{id:string;text:string;is_correct:boolean}[] };
    type CheckFixture = { id: string; title: string; instructions: string; pass_score: number; attempt_limit: number;
      time_limit_minutes: number | null; questions: AuthoredQuestion[]; revision: number; status: string };
    let check: CheckFixture | null = null;
    let assignmentMade = false;
    let revisionOneQuestion: AuthoredQuestion | null = null;
    const savedResult = () => ({ id:assignmentId, check_id:check!.id, title:'Safety check', revision:1,
      due_at:null, status:'failed', attempt_limit:2, attempts_count:1, score_percent:0, passed:false,
      user_id:ids.learner, employee_label:'Learner Synthetic', attempts:[{
        id:firstAttemptId, assignment_id:assignmentId, number:1, status:'submitted', started_at:startedAt,
        deadline_at:null, completed_at:startedAt, score_percent:0, passed:false, earned_points:0, total_points:1,
        answers:[{question_id:revisionOneQuestion!.id,selected_choice_ids:[revisionOneQuestion!.choices[1].id]}],
      }] });
    workspace.onGet('/v1/knowledge-checks/', () => ({ json:{items:check?[check]:[],has_more:false} }));
    workspace.get('/v1/users', { users:[{ id:ids.learner, tenant_id:ids.tenant, first_name:'Synthetic', last_name:'Learner',
      email:'learner@example.invalid', personnel_number:'SYN-001', role:'student', roles:['student'], is_active:true, status:'active',
      position_id:null, telegram_id:null, has_login_access:true, last_login:null, created_at:startedAt, tenant:null,
      welcome_email_status:null, welcome_email_failure_category:null }], total:1,page:1,per_page:20 });
    await workspace.install();
    await page.setViewportSize({width,height:900});
    await page.goto('/knowledge-checks');
    await page.getByRole('button', {name:'Create',exact:true}).click();
    await page.getByLabel('Title', {exact:true}).fill('Safety check');
    await page.getByLabel('Instructions').fill('Select one answer');
    await page.getByLabel('Attempt limit').fill('2');
    await page.getByLabel('Question', {exact:true}).fill('What should you do?');
    await page.getByLabel('Choice 1').fill('Stop work');
    await page.getByLabel('Choice 2').fill('Continue work');
    workspace.command('POST', '/v1/knowledge-checks/', ({body}) => {
      const request = body as Omit<CheckFixture, 'revision' | 'status'>;
      expect(request.id).toMatch(/^[0-9a-f-]{36}$/i);
      expect(request.id).not.toBe(assignmentId);
      expect(request.title).toBe('Safety check');
      expect(request.attempt_limit).toBe(2);
      expect(request.questions[0].type).toBe('MCQ');
      expect(request.questions[0].choices.map(choice => [choice.text,choice.is_correct])).toEqual([['Stop work',true],['Continue work',false]]);
      revisionOneQuestion = request.questions[0];
      check = {...request,revision:1,status:'draft'};
      return {json:check};
    });
    await page.getByRole('button', {name:'Save',exact:true}).click();
    await expect(page.getByRole('button',{name:'Publish'})).toBeEnabled();
    const created = check as CheckFixture | null;
    expect(created).not.toBeNull();
    const id = created!.id;
    workspace.onGet(`/v1/knowledge-checks/${id}`, () => ({json:check}));
    workspace.onGet(`/v1/knowledge-checks/${id}/results`, () => ({json:{items:assignmentMade?[savedResult()]:[],has_more:false}}));
    workspace.command('POST', `/v1/knowledge-checks/${id}/publish`, ({body}) => {
      expect(body).toEqual({expected_revision:1}); check = {...check!,status:'published'}; return {json:check};
    });
    await page.getByRole('button',{name:'Publish'}).click();
    await expect(page.getByLabel('Learner Synthetic · SYN-001')).toBeVisible();
    await expect(page.getByLabel('Author Synthetic')).toHaveCount(0);
    await page.getByLabel('Learner Synthetic · SYN-001').check();
    workspace.command('POST', `/v1/knowledge-checks/${id}/assign`, ({body}) => {
      expect(body).toEqual({expected_revision:1,user_ids:[ids.learner],due_at:null});
      assignmentMade=true; return {json:{items:[{id:assignmentId,check_id:id,title:'Safety check',revision:1,due_at:null,
        status:'assigned',attempt_limit:2,attempts_count:0,score_percent:null,passed:null}],has_more:false}};
    });
    await page.getByRole('button',{name:'Assign employees'}).click();
    await expect(page.getByText('Assignment processed.')).toBeVisible();
    await page.getByRole('button',{name:'Results',exact:true}).click();
    await expect(page.getByText('Attempts 1: Submitted · 0%')).toBeVisible();
    await page.getByLabel('Title',{exact:true}).fill('Safety check revision 2');
    workspace.command('PUT', `/v1/knowledge-checks/${id}`, ({body}) => {
      const request = body as Omit<CheckFixture,'id'|'revision'|'status'> & {expected_revision:number};
      expect(request.expected_revision).toBe(1); expect(request.title).toBe('Safety check revision 2');
      const {expected_revision: _revision, ...content}=request;
      check={...content,id,revision:2,status:'draft'}; return {json:check};
    });
    await page.getByRole('button',{name:'Save',exact:true}).click();
    workspace.command('POST', `/v1/knowledge-checks/${id}/publish`, ({body}) => {
      expect(body).toEqual({expected_revision:2}); check={...check!,status:'published'}; return {json:check};
    });
    await page.getByRole('button',{name:'Publish'}).click();
    await page.getByRole('button',{name:'Results',exact:true}).click();
    await expect(page.getByText('Attempts 1: Submitted · 0%')).toBeVisible();
    await expect(page.getByText(/Learner Synthetic.*Revision 1/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    workspace.assertIsolated();
  });
}

test('student cannot open the author route', async ({page,context}) => {
  const workspace=new SyntheticWorkspace(context,'en');
  workspace.learner();
  await workspace.install();
  await page.goto('/knowledge-checks');
  await expect(page).toHaveURL(/\/student(?:\?.*)?$/);
  await expect(page.getByRole('button',{name:'Create',exact:true})).toHaveCount(0);
  expect(workspace.matching('GET','/v1/knowledge-checks/')).toHaveLength(0);
  workspace.assertIsolated();
});

test('methodologist cannot open a learner assignment', async ({page,context}) => {
  const workspace=new SyntheticWorkspace(context,'en');
  workspace.role='methodologist';
  for (const path of ['/v1/admin/onboarding-status','/v1/admin/learning-actions','/v1/courses',
    '/v1/ai/jobs','/v1/admin/mandatory-training/summary']) {
    workspace.onGet(path, () => ({status:503,json:{detail:'Synthetic destination unavailable'}}));
  }
  await workspace.install();
  await page.goto(`/my-knowledge-checks/${assignmentId}`);
  await expect(page).toHaveURL(/\/dashboard(?:\?.*)?$/);
  await expect(page.getByRole('heading',{name:'Tasks'})).toBeVisible();
  expect(workspace.matching('GET',`/v1/knowledge-checks/assignments/${assignmentId}`)).toHaveLength(0);
  workspace.assertIsolated();
});
