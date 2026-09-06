'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { AlertTriangle, BarChart3, ChevronDown, RotateCcw } from 'lucide-react';
import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';
import { Modal } from '@/components/ui/modal';
import { useAuthStore } from '@/store/authStore';
import { getCourseInsights, getEnrollmentInsights, saveQuestionReview } from './api';
import { useLearningInsightsT } from './i18n';
import type {
  AttemptDetail,
  CourseInsights,
  LearningInsightsFilters,
  QuestionStats,
  Review,
  ReviewStatus,
} from './types';

const STATUSES: ReviewStatus[] = [
  'unreviewed',
  'train_staff',
  'review_question',
  'improve_material',
  'resolved',
];

type ReviewEvent = { key: string; review?: Review; saving?: boolean };
type ReviewListener = (event: ReviewEvent) => void;

// This is a short-lived in-memory event channel only. It shares a successful
// response between mounted copies without becoming a persistent review cache.
const reviewListeners = new Set<ReviewListener>();
// One in-flight mutation per exact tenant/course/question. This prevents two
// mounted copies from racing; entries are removed on both success and failure.
const pendingReviews = new Set<string>();

function publishReview(event: ReviewEvent): void {
  reviewListeners.forEach((listener) => listener(event));
}

function subscribeToReviews(listener: ReviewListener): () => void {
  reviewListeners.add(listener);
  return () => reviewListeners.delete(listener);
}

function makeScopeKey(values: Record<string, string | null | undefined>): string {
  return JSON.stringify(values);
}

function makeReviewKey(tenantId: string | null | undefined, courseId: string, questionKey: string): string {
  return makeScopeKey({ tenantId, courseId, questionKey });
}

function releaseLabel(
  releaseId: string | null,
  text: ReturnType<typeof useLearningInsightsT>['text'],
): string {
  return releaseId ? text('release', { id: releaseId }) : text('releaseUnavailable');
}

export function canUseLearningInsights(
  user: { role?: string | null; tenant_id?: string | null } | null,
): boolean {
  return Boolean(
    user
      && user.tenant_id
      && user.role === 'methodologist',
  );
}

export function LearningInsightsPanel(props: {
  courseId?: string;
  departmentId?: string;
  positionId?: string;
  dateFrom?: string;
  dateTo?: string;
}) {
  const user = useAuthStore((state) => state.user);
  const { text, status } = useLearningInsightsT();
  const [data, setData] = useState<CourseInsights | null>(null);
  const [dataScopeKey, setDataScopeKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const allowed = canUseLearningInsights(user);
  const tenantId = user?.tenant_id ?? null;
  const userId = user?.user_id ?? null;
  const scopeKey = makeScopeKey({
    tenantId,
    userId,
    role: user?.role,
    courseId: props.courseId,
    departmentId: props.departmentId,
    positionId: props.positionId,
    dateFrom: props.dateFrom,
    dateTo: props.dateTo,
  });
  const load = useCallback(async () => {
    if (!props.courseId || !allowed) return;

    const request = ++generation.current;
    setLoading(true);
    setError(null);

    try {
      const filters: LearningInsightsFilters = {
        departmentId: props.departmentId,
        positionId: props.positionId,
        dateFrom: props.dateFrom,
        dateTo: props.dateTo,
      };
      const result = await getCourseInsights(props.courseId, filters);
      if (request === generation.current) {
        setData(result);
        setDataScopeKey(scopeKey);
      }
    } catch (cause: any) {
      if (request === generation.current) {
        setError(String(cause?.response?.data?.detail || cause?.message || text('unavailable')));
      }
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [
    allowed,
    props.courseId,
    props.departmentId,
    props.positionId,
    props.dateFrom,
    props.dateTo,
    scopeKey,
    text,
  ]);

  useEffect(() => {
    setData(null);
    setDataScopeKey(null);
    setError(null);
    setLoading(false);

    if (props.courseId && allowed) void load();

    return () => {
      generation.current += 1;
    };
  }, [allowed, load, props.courseId, scopeKey]);

  const visibleData = dataScopeKey === scopeKey ? data : null;

  if (!allowed) return null;
  if (!props.courseId) {
    return (
      <Card>
        <CardContent className="p-5 text-sm text-muted-foreground">
          {text('selectCourse')}
        </CardContent>
      </Card>
    );
  }
  if (loading && !visibleData) {
    return (
      <Card>
        <CardContent className="p-5 text-sm text-muted-foreground">
          {text('loading')}
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-5 text-sm text-destructive">
          <span>{error}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => void load()}>
            <RotateCcw className="mr-2 h-4 w-4" aria-hidden="true" />
            {text('retry')}
          </Button>
        </CardContent>
      </Card>
    );
  }
  if (!visibleData) return null;

  return (
    <Card data-testid="learning-insights-panel">
      <CardHeader className="space-y-2">
        <CardTitle className="flex items-center gap-2">
          <BarChart3 className="h-5 w-5" aria-hidden="true" />
          {text('title')}
        </CardTitle>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>{text('cohort')}</span>
          <span>{text('basis')}</span>
          <span>{text('employees', { count: visibleData.included_employees })}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {visibleData.excluded_attempts > 0 && (
          <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
            {text('excluded', { count: visibleData.excluded_attempts })}
          </p>
        )}
        {visibleData.questions?.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">{text('empty')}</p>
        ) : visibleData.questions?.map((question) => (
          <QuestionStatCard
            key={question.question_key}
            question={question}
            tenantId={tenantId}
            courseId={visibleData.course_id}
            text={text}
            status={status}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function QuestionStatCard({
  question,
  tenantId,
  courseId,
  text,
  status,
}: {
  question: QuestionStats;
  tenantId: string | null;
  courseId: string;
  text: ReturnType<typeof useLearningInsightsT>['text'];
  status: ReturnType<typeof useLearningInsightsT>['status'];
}) {
  const latestPercentage = question.latest_incorrect_percent === null
    ? '—'
    : `${question.latest_incorrect_percent}%`;
  const reviewKey = makeReviewKey(tenantId, courseId, question.question_key);

  return (
    <QuestionReview
      attemptId={question.example_attempt_id}
      questionId={question.question_id}
      reviewKey={reviewKey}
      review={question.review}
      text={text}
      status={status}
    >
      {({ control, error }) => (
        <article className="rounded-lg border border-border p-4" data-testid="learning-insight-question">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="font-medium text-foreground">{question.text}</p>
              <p className="mt-1 text-xs text-muted-foreground">{question.quiz_title}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {releaseLabel(question.content_release_id, text)}
              </p>
            </div>
            {control}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <Metric
              label={text('first')}
              value={`${question.incorrect}/${question.respondents} (${question.incorrect_percent}%)`}
            />
            <Metric
              label={text('latest')}
              value={`${question.latest_incorrect}/${question.latest_respondents} (${latestPercentage})`}
            />
            <Metric label={text('improved')} value={String(question.improved)} />
            <Metric label={text('regressed')} value={String(question.regressed)} />
          </div>
          {(question.latest_incorrect_percent === null || question.latest_unavailable > 0) && (
            <p className="mt-3 text-xs text-muted-foreground">
              {text('latestUnavailable', { count: question.latest_unavailable })}
            </p>
          )}
          {question.respondents < 5 && (
            <p className="mt-3 flex gap-2 text-xs text-amber-700">
              <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />
              {text('lowSample')}
            </p>
          )}
          {question.incorrect > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">{text('massError')}</p>
          )}
          {question.wrong_choices.length > 0 && (
            <p className="mt-3 text-sm">
              <span className="font-medium">{text('wrongChoices')}:</span>{' '}
              {question.wrong_choices.map((choice) => `${choice.text} (${choice.count})`).join(', ')}
            </p>
          )}
          {error}
        </article>
      )}
    </QuestionReview>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 font-medium tabular-nums">{value}</div>
    </div>
  );
}

function QuestionReview({
  attemptId,
  questionId,
  reviewKey,
  review: initialReview,
  text,
  status,
  children,
}: {
  attemptId: string;
  questionId: string;
  reviewKey: string;
  review: Review;
  text: ReturnType<typeof useLearningInsightsT>['text'];
  status: ReturnType<typeof useLearningInsightsT>['status'];
  children: (value: { review: Review; control: ReactNode; error: ReactNode }) => ReactNode;
}) {
  const [review, setReview] = useState(initialReview);
  const [saving, setSaving] = useState(() => pendingReviews.has(reviewKey));
  const [failedStatus, setFailedStatus] = useState<ReviewStatus | null>(null);
  const saveGeneration = useRef(0);
  const mounted = useRef(true);
  const currentReviewKey = useRef(reviewKey);
  currentReviewKey.current = reviewKey;
  const initialReviewStatus = initialReview.status;
  const initialReviewUpdatedAt = initialReview.updated_at;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      saveGeneration.current += 1;
    };
  }, []);

  useEffect(() => {
    saveGeneration.current += 1;
    setSaving(pendingReviews.has(reviewKey));
    setReview({ status: initialReviewStatus, updated_at: initialReviewUpdatedAt });
    setFailedStatus(null);
  }, [initialReviewStatus, initialReviewUpdatedAt, reviewKey]);

  useEffect(() => subscribeToReviews((event) => {
    if (event.key !== reviewKey) return;
    if (event.review) setReview(event.review);
    if (event.saving !== undefined) setSaving(event.saving);
    if (event.review || event.saving === true) setFailedStatus(null);
  }), [reviewKey]);

  const save = async (next: ReviewStatus) => {
    if (pendingReviews.has(reviewKey) || next === review.status) return;

    const request = ++saveGeneration.current;
    pendingReviews.add(reviewKey);
    publishReview({ key: reviewKey, saving: true });
    setSaving(true);
    setFailedStatus(null);

    try {
      const saved = await saveQuestionReview(attemptId, questionId, next);
      // Subscribers filter the exact tenant/course/question key. A mounted
      // copy still receives the committed result if the originating dialog closed.
      publishReview({ key: reviewKey, review: saved });
    } catch {
      if (mounted.current && request === saveGeneration.current && currentReviewKey.current === reviewKey) {
        setFailedStatus(next);
      }
    } finally {
      pendingReviews.delete(reviewKey);
      publishReview({ key: reviewKey, saving: false });
    }
  };

  const control = (
    <label className="text-sm text-muted-foreground">
      <span className="sr-only">{text('review')}</span>
      <select
        aria-label={text('review')}
        value={review.status}
        disabled={saving}
        onChange={(event) => void save(event.target.value as ReviewStatus)}
        className="h-9 rounded-md border border-input bg-background px-2 text-sm disabled:opacity-60"
      >
        {STATUSES.map((item) => (
          <option key={item} value={item}>
            {saving ? text('pending') : status(item)}
          </option>
        ))}
      </select>
    </label>
  );
  const error = failedStatus && (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-destructive">
      <span>{text('saveFailed')}</span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={saving}
        onClick={() => void save(failedStatus)}
      >
        {text('retry')}
      </Button>
    </div>
  );

  return <>{children({ review, control, error })}</>;
}

export function LearnerAnswers({
  enrollmentId,
  onClose,
}: {
  enrollmentId: string | null;
  onClose: () => void;
}) {
  const user = useAuthStore((state) => state.user);
  const { text, status } = useLearningInsightsT();
  const [data, setData] = useState<Awaited<ReturnType<typeof getEnrollmentInsights>> | null>(null);
  const [dataScopeKey, setDataScopeKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const allowed = canUseLearningInsights(user);
  const tenantId = user?.tenant_id ?? null;
  const userId = user?.user_id ?? null;
  const scopeKey = makeScopeKey({
    tenantId,
    userId,
    role: user?.role,
    enrollmentId,
  });

  const load = useCallback(async () => {
    if (!enrollmentId || !allowed) return;

    const request = ++generation.current;
    setLoading(true);
    setError(null);

    try {
      const result = await getEnrollmentInsights(enrollmentId);
      if (request === generation.current) {
        setData(result);
        setDataScopeKey(scopeKey);
      }
    } catch (cause: any) {
      if (request === generation.current) {
        setError(String(cause?.response?.data?.detail || cause?.message || text('unavailable')));
      }
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [allowed, enrollmentId, scopeKey, text]);

  useEffect(() => {
    setData(null);
    setDataScopeKey(null);
    setError(null);
    setLoading(false);

    if (enrollmentId && allowed) void load();

    return () => {
      generation.current += 1;
    };
  }, [allowed, enrollmentId, load, scopeKey]);

  if (!allowed || !enrollmentId) return null;

  const visibleData = dataScopeKey === scopeKey ? data : null;

  return (
    <Modal
      open
      onClose={onClose}
      title={visibleData ? `${text('answers')}: ${visibleData.user_name}` : text('answers')}
      description={visibleData?.course_title}
      className="max-w-3xl"
    >
      <div className="space-y-4">
        {loading && !visibleData ? (
          <p className="text-sm text-muted-foreground">{text('loading')}</p>
        ) : error ? (
          <div className="space-y-3 text-sm text-destructive">
            <p>{error}</p>
            <Button type="button" variant="outline" onClick={() => void load()}>
              {text('retry')}
            </Button>
          </div>
        ) : visibleData?.attempts?.length === 0 ? (
          <p className="text-sm text-muted-foreground">{text('empty')}</p>
        ) : visibleData?.attempts?.map((attempt) => (
          <AttemptCard
            key={attempt.id}
            attempt={attempt}
            courseId={visibleData.course_id}
            tenantId={tenantId}
            canEdit={user?.role === 'methodologist'}
            text={text}
            status={status}
          />
        ))}
      </div>
    </Modal>
  );
}

function AttemptCard({
  attempt,
  courseId,
  tenantId,
  canEdit,
  text,
  status,
}: {
  attempt: AttemptDetail;
  courseId: string;
  tenantId: string | null;
  canEdit: boolean;
  text: ReturnType<typeof useLearningInsightsT>['text'];
  status: ReturnType<typeof useLearningInsightsT>['status'];
}) {
  const [expanded, setExpanded] = useState(true);
  const detailsId = `learning-insights-attempt-${attempt.id}`;

  return (
    <section className="rounded-lg border border-border">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center justify-between gap-3 p-4 text-left"
      >
        <span>
          <span className="font-medium">{text('attempt', { count: attempt.attempt_number })}</span>
          <span className="ml-2 text-sm text-muted-foreground">
            {new Date(attempt.completed_at).toLocaleDateString()}
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">{attempt.quiz_title}</span>
          <span className="mt-1 block text-xs text-muted-foreground">
            {releaseLabel(attempt.content_release_id, text)}
          </span>
        </span>
        <ChevronDown
          className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      <div id={detailsId} hidden={!expanded}>
        {expanded && (
          <div className="space-y-3 border-t border-border p-4">
            <div className="flex flex-wrap gap-2 text-sm">
              <span>{text('score', { count: attempt.score_percent })}</span>
              <span className={attempt.passed ? 'text-emerald-700' : 'text-muted-foreground'}>
                {attempt.passed ? text('passed') : text('notPassed')}
              </span>
            </div>
            {attempt.evidence_status !== 'verified' ? (
              <p className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
                {text('evidenceUnavailable')}
              </p>
            ) : attempt.questions.length === 0 ? (
              <p className="text-sm text-muted-foreground">{text('noQuestions')}</p>
            ) : attempt.questions.map((question) => (
              <QuestionReview
                key={question.question_key}
                attemptId={attempt.id}
                questionId={question.question_id}
                reviewKey={makeReviewKey(tenantId, courseId, question.question_key)}
                review={question.review}
                text={text}
                status={status}
              >
                {({ control, error }) => (
                  <article className="rounded-md bg-muted/50 p-3">
                    <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
                      <div>
                        <p className="font-medium">{question.text}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {attempt.quiz_title} · {releaseLabel(attempt.content_release_id, text)}
                        </p>
                      </div>
                      {control}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {question.is_correct
                        ? text('byTestKey')
                        : `${question.points_earned}/${question.points_possible}`}
                    </p>
                    <ul className="mt-3 space-y-2 text-sm">
                      {question.choices.map((choice) => (
                        <li key={choice.id} className="rounded border border-border bg-background p-2">
                          <span>{choice.text}</span>
                          <span className="ml-2 text-xs text-muted-foreground">
                            {choice.selected ? text('selected') : ''}
                            {choice.selected && choice.correct ? ' · ' : ''}
                            {choice.correct ? text('correct') : ''}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {question.explanation && (
                      <p className="mt-3 text-sm text-muted-foreground">
                        <span className="font-medium text-foreground">{text('explanation')}:</span>{' '}
                        {question.explanation}
                      </p>
                    )}
                    {canEdit && attempt.lesson_id && (
                      <a
                        className="mt-3 inline-block text-sm text-primary hover:underline"
                        href={`/courses/${courseId}/edit?lessonId=${encodeURIComponent(attempt.lesson_id)}`}
                      >
                        {text('editCourse')}
                      </a>
                    )}
                    {error}
                  </article>
                )}
              </QuestionReview>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
