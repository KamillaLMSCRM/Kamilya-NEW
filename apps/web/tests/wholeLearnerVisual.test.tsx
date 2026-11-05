import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), fetch: vi.fn(), list: vi.fn(), request: vi.fn(), start: vi.fn(),
  decision: vi.fn(), progress: vi.fn(), test: vi.fn(),
  t: (key: string) => key, params: { id: 'course-1', quizId: 'quiz-1' },
}));
vi.mock('@/lib/api', () => ({ api: { get: mocks.get, post: mocks.post } }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ t: mocks.t, tp: (key: string, count: number) => `${count} ${key}`, lang: 'en' }) }));
vi.mock('@/store/languageStore', () => ({ useLanguageStore: (selector: (state: { lang: 'en' }) => unknown) => selector({ lang: 'en' }) }));
vi.mock('next/navigation', () => ({ useParams: () => mocks.params, useSearchParams: () => new URLSearchParams('courseId=course-1&lessonId=lesson-1'), useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { success: vi.fn(), error: vi.fn(), dismiss: vi.fn() } }));
vi.mock('@/lib/useIdleTimeout', () => ({ useIdleTimeout: () => ({ warningSeconds: null }) }));
vi.mock('@/lib/courseApproval', () => ({ listApprovalRequests: mocks.list, getApprovalRequest: mocks.request, getScopedReviewRequest: mocks.request, startReviewAttempt: mocks.start, submitReviewDecision: mocks.decision, saveReviewProgress: mocks.progress, submitReviewTest: mocks.test }));

import StudentPage from '@/app/student/page';
import MyCoursesPage from '@/app/my-courses/page';
import MyQuizzesPage from '@/app/my-quizzes/page';
import CoursePlayerPage from '@/app/courses/[id]/page';
import QuizPlayerPage from '@/app/courses/quiz/[quizId]/page';
import QuizPreviewPage from '@/app/courses/quiz/[quizId]/preview/page';
import CertificatesPage from '@/app/certificates/page';
import CourseReviewPage from '@/app/course-review/page';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';
import { EvidenceConfirmationPanel } from '@/features/training-evidence/EvidenceConfirmationPanel';
import { useAuthStore } from '@/store/authStore';

const assignment = {
  enrollment_id: 'occurrence-1', course_id: 'course-1', title: 'Assigned safety course', description: 'Retained assignment description',
  can_resume: true, enrollment_status: 'in_progress', status: 'published', delivery_type: 'native',
  progress_percent: 25, total_lessons: 4, completed_lessons: 1, enrolled_at: '2026-10-01',
  resume_href: '/courses/course-1?enrollmentId=occurrence-1', assignment_due_at: null, assignment_source: 'manual',
};
const lesson = { id: 'lesson-1', title: 'Read the procedure', content: '# Read the procedure\n\nRetained lesson paragraph.', order_index: 0, content_type: 'text' };
const quiz = { id: 'quiz-1', lesson_id: 'lesson-1', title: 'Safety assessment', pass_score: 80, time_limit: null, attempt_limit: 3, questions: [{ id: 'question-1', text: 'Choose a safe action', type: 'MCQ', points: 1, explanation: null, order_index: 0, choices: [{ id: 'choice-1', text: 'Follow the procedure', order_index: 0 }] }] };
const snapshot = { schema_version: 1, release_version: 3, course: { id: 'course-1', title: 'Frozen safety course' }, modules: [{ id: 'module-1', title: 'Safety module', order_index: 0, lessons: [{ ...lesson, quizzes: [] }] }] };
const request = { request_id: 'request-12345678', revision_id: 'revision-1', outcome: 'pending', reviewers: [{ reviewer_id: 'learner-1' }] };
const event = { id: 'event-1', procedure_type: 'training', confirmation_status: 'pending', occurred_at: '2026-10-01', release_version: 3, confirmation_statement: 'I confirm this specific training event.' };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ accessToken: 'learner-token', user: { user_id: 'learner-1', tenant_id: 'tenant-1', email: 'learner@example.test', role: 'student' } as never, initialized: true });
  mocks.get.mockImplementation(async (path: string) => {
    if (path.endsWith('/signed-scans')) return { data: { status: 'awaiting_return', scans: [] } };
    if (path.includes('/events/mine/')) return { data: event };
    if (path === '/v1/student/dashboard') return { data: { enrolled_courses: [assignment] } };
    return { data: [] };
  });
  mocks.post.mockResolvedValue({ data: { challenge_id: 'challenge-1' } });
  mocks.list.mockResolvedValue([request]);
  mocks.request.mockResolvedValue(request);
  mocks.start.mockResolvedValue({ attempt_id: 'review-attempt-1', snapshot, snapshot_sha256: 'frozen-sha', activity_state: 'in_progress', lesson_position: 0, next_sequence: 4 });
  mocks.fetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith('/v1/student/dashboard')) return json({ full_name: 'Learner', enrolled_courses: [assignment], total_courses: 4, completed_courses: 1, total_progress_percent: 25, certificates_count: null });
    if (url.endsWith('/v1/courses/course-1')) return json({ id: 'course-1', title: 'Assigned safety course', delivery_type: 'native', status: 'published' });
    if (url.endsWith('/structure')) return json({ modules: [{ id: 'module-1', title: 'Safety module', lessons: [lesson] }] });
    if (url.endsWith('/completed-ids')) return json({ completed_lesson_ids: [] });
    if (url.endsWith('/access-window')) return json(null);
    if (url.endsWith('/v1/quizzes/quiz-1')) return json(quiz);
    if (url.endsWith('/attempts')) return json([]);
    return json({}, 404);
  });
  vi.stubGlobal('fetch', mocks.fetch);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('learner screen-owned compositions', () => {
  it('puts the exact next occurrence before supporting statistics and keeps unknown totals neutral', async () => {
    const nextAssignment = { ...assignment, course_id: '123e4567-e89b-42d3-a456-426614174000', resume_href: '/courses/123e4567-e89b-42d3-a456-426614174000?lessonId=123e4567-e89b-42d3-a456-426614174001' };
    mocks.fetch.mockResolvedValueOnce(json({ full_name: 'Learner', enrolled_courses: [nextAssignment], total_courses: 4, completed_courses: 1, total_progress_percent: 25, certificates_count: null }));
    const { container } = render(<StudentPage />);
    await screen.findByText('dashboard.certificatesCount');
    const next = screen.getByRole('heading', { name: assignment.title, level: 2 }).closest('[data-workspace-panel]');
    const stats = container.querySelectorAll('[data-workspace-stat]');
    expect(next).toContainElement(screen.getAllByRole('link', { name: 'courses.continueCourse' })[0]);
    expect(stats).toHaveLength(4);
    expect(stats[3]).toHaveTextContent('—');
    expect(next!.compareDocumentPosition(stats[0]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'courses.continueCourse' })[0]).toHaveAttribute('href', nextAssignment.resume_href);
  });

  it('keeps course filters in a wrapping toolbar and result actions in each paper card', async () => {
    render(<MyCoursesPage />);
    const filter = await screen.findByRole('button', { name: 'student.completed' });
    expect(filter.closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: assignment.title }).closest('.rounded-2xl')).toContainElement(screen.getByRole('link', { name: 'courses.continueCourse' }));
    fireEvent.click(filter);
    expect(screen.getByText('student.completed — common.none').closest('[data-workspace-empty]')).not.toBeNull();
  });

  it('separates expired assessment rows from their disabled action without a launch link', async () => {
    mocks.get.mockResolvedValue({ data: [{ quiz_id: 'expired-quiz', quiz_title: 'Expired assessment', module_title: 'Safety module', lesson_title: lesson.title, pass_score: 80, deferral_days: 2, attempt_limit: 3, attempts_count: 1, passed: false, is_expired: true }] });
    render(<MyQuizzesPage />);
    const title = await screen.findByRole('heading', { name: 'Expired assessment' });
    const row = title.closest('article')!;
    expect(row.closest('[data-workspace-panel]')).not.toBeNull();
    expect(within(row).getByRole('button', { name: 'quiz.notAvailable' })).toBeDisabled();
    expect(within(row).queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'student.toComplete' })).toHaveAttribute('href', '#pending-quizzes');
  });

  it('keeps the reader outline distinct from the lesson paper, one title, and its footer', async () => {
    render(<CoursePlayerPage />);
    const title = await screen.findByRole('heading', { level: 1, name: lesson.title });
    const paper = title.closest('[data-workspace-panel]')!;
    expect(paper.querySelector('article')).toHaveTextContent('Retained lesson paragraph.');
    expect(screen.getAllByRole('heading', { name: lesson.title })).toHaveLength(1);
    expect(paper.querySelector('footer')).toContainElement(await screen.findByRole('button', { name: 'courses.finishCourse' }));
    expect(screen.getByRole('navigation')).not.toContainElement(title);
  });

  it('groups assessment navigation, question paper and footer without exposing grading keys', async () => {
    render(<QuizPlayerPage />);
    const title = await screen.findByRole('heading', { level: 2, name: quiz.questions[0].text });
    expect(title.closest('[data-workspace-panel]')).toContainElement(screen.getByRole('radio'));
    expect(screen.getByRole('navigation')).toContainElement(screen.getByRole('button', { name: '1' }));
    const finish = screen.getByRole('button', { name: 'quiz.finish' });
    expect(finish).toBeDisabled();
    fireEvent.click(screen.getByRole('radio'));
    expect(finish).toBeEnabled();
    expect(finish.closest('[data-workspace-toolbar]')).not.toBeNull();
    expect(screen.queryByText('quiz.correctAnswer')).not.toBeInTheDocument();
  });

  it('keeps privileged preview notice, question papers, and preview-only submission', async () => {
    useAuthStore.setState({ user: { user_id: 'author-1', tenant_id: 'tenant-1', role: 'methodologist' } as never });
    mocks.fetch.mockImplementation(async (input: RequestInfo | URL) => String(input).endsWith('/preview-submit') ? json({ score_percent: 100, earned_points: 1, total_points: 1, passed: true, graded_answers: [] }) : json(quiz));
    render(<QuizPreviewPage />);
    const question = await screen.findByRole('heading', { name: quiz.questions[0].text });
    expect(question.closest('[data-workspace-panel]')).toContainElement(screen.getByRole('radio'));
    expect(screen.getByText('quiz.previewNotice')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio'));
    fireEvent.click(screen.getByRole('button', { name: 'quiz.previewFinish' }));
    await screen.findByText('quiz.previewPassed');
    const writes = mocks.fetch.mock.calls.filter(([, init]) => init?.method === 'POST');
    expect(writes).toHaveLength(1);
    expect(String(writes[0][0])).toMatch(/\/preview-submit$/);
  });

  it('renders certificate document rows with wrapping verification/download actions', async () => {
    mocks.fetch.mockResolvedValue(json([{ id: 'certificate-1', course_title: 'Safety qualification', certificate_number: 'CERT/42', issued_at: '2026-10-01', expires_at: null, status: 'active' }]));
    render(<CertificatesPage />);
    const title = await screen.findByRole('heading', { name: 'Safety qualification' });
    const row = title.closest('article')!;
    const verify = within(row).getByRole('link', { name: 'certificates.openVerification' });
    expect(verify).toHaveAttribute('href', '/verify/certificate/CERT%2F42');
    expect(verify.parentElement).toHaveClass('flex-wrap');
    expect(within(row).getByRole('button', { name: 'common.download' })).toBeEnabled();
    expect(row.closest('[data-workspace-panel]')).not.toBeNull();
  });

  it('does not render a confirmed-empty certificate state after a load failure', async () => {
    mocks.fetch.mockRejectedValue(new Error('offline'));
    render(<CertificatesPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('common.loadFailed');
    expect(screen.queryByText('certificates.noCertificates')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'common.retry' })).toBeEnabled();
    mocks.fetch.mockResolvedValue(json([]));
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(screen.getByRole('status')).toHaveTextContent('common.loading');
    expect(await screen.findByText('certificates.noCertificates')).toBeInTheDocument();
  });

  it('retains certificate documents while the same session refreshes its token', async () => {
    mocks.fetch.mockResolvedValueOnce(json([{ id: 'certificate-1', course_title: 'Retained certificate', certificate_number: 'CERT-42', issued_at: '2026-10-01', expires_at: null, status: 'active' }]));
    render(<CertificatesPage />);
    await screen.findByRole('heading', { name: 'Retained certificate' });
    mocks.fetch.mockImplementationOnce(() => new Promise<Response>(() => {}));
    act(() => { useAuthStore.setState({ accessToken: 'refreshed-token' }); });
    expect(screen.getByRole('heading', { name: 'Retained certificate' })).toBeInTheDocument();
    expect(screen.queryByText('common.loading')).not.toBeInTheDocument();
  });

  it('shows review inbox loading before document rows and keeps the exact request destination', async () => {
    render(<CourseReviewPage />);
    expect(screen.getByRole('status')).toHaveTextContent('common.loading');
    const link = await screen.findByRole('link', { name: 'courseApproval.openReview' });
    expect(link).toHaveAttribute('href', '/course-review-requests/request-12345678');
    expect(link.closest('article')?.closest('[data-workspace-panel]')).not.toBeNull();
    expect(screen.queryByText('courseApproval.noPendingReviews')).not.toBeInTheDocument();
  });

  it('keeps snapshot metadata, reading, and explicit decision confirmation as separate papers', async () => {
    render(<ReviewRequestScreen requestId={request.request_id} />);
    await screen.findByText('Frozen safety course');
    const details = screen.getByText('frozen-sha').closest('details')!;
    fireEvent.click(within(details).getByText(/Snapshot/, { selector: 'summary' }));
    expect(details).toHaveAttribute('open');
    expect(screen.getByRole('navigation')).not.toContainElement(screen.getByRole('heading', { name: lesson.title }));
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'courseApproval.approve' }));
    expect(mocks.decision).not.toHaveBeenCalled();
    expect(await screen.findByRole('dialog')).toHaveTextContent('frozen-sha');
  });

  it('groups event metadata, document tools, and event-bound OTP without replacing the challenge payload', async () => {
    render(<EvidenceConfirmationPanel eventId="event-1" activityTitle="Training" activityKind="course" continueHref="/my-courses" />);
    await screen.findByText(event.confirmation_statement);
    expect(screen.getByText('evidenceConfirmation.activity').closest('dl')?.children).toHaveLength(4);
    expect(screen.getByRole('button', { name: 'evidenceConfirmation.downloadPdf' }).closest('section')).not.toContainElement(screen.getByText('evidenceConfirmation.signedCopy'));
    fireEvent.click(screen.getByRole('button', { name: 'evidenceConfirmation.requestCode' }));
    const code = await screen.findByLabelText('evidenceConfirmation.codeLabel');
    expect(code).toHaveAttribute('autoComplete', 'one-time-code');
    expect(mocks.post).toHaveBeenCalledWith('/v1/training-evidence/step-up/events/event-1/request', {});
    expect(screen.getByRole('link', { name: 'evidenceConfirmation.continue' }).closest('footer')).not.toBeNull();
  });

  it('keeps not-required evidence distinct from confirmed evidence and never offers OTP', async () => {
    mocks.get.mockImplementation(async (path: string) => ({ data: path.endsWith('/signed-scans') ? { status: 'awaiting_return', scans: [] } : { ...event, confirmation_status: 'not_required' } }));
    render(<EvidenceConfirmationPanel eventId="event-1" activityTitle="Training" activityKind="course" />);
    await waitFor(() => expect(screen.queryByText('evidenceConfirmation.loading')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'evidenceConfirmation.requestCode' })).not.toBeInTheDocument();
    expect(screen.queryByText('evidenceConfirmation.status.confirmed')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'evidenceConfirmation.downloadPdf' })).toBeEnabled();
  });
});
