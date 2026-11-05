'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle2, XCircle } from 'lucide-react';
import { Badge, Button, Card, CardContent } from '@/components/ui';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';
import { isSingleAnswerQuestionType } from '@/lib/quizChoice';
import { getRoleHome } from '@/lib/rolePolicy';
import { useAuthStore } from '@/store/authStore';
import { WorkspaceEmpty, WorkspacePage, WorkspacePanel, WorkspaceToolbar } from '@/features/workspace-design';

interface QuizChoice {
  id: string;
  text: string;
  order_index: number;
}

interface QuizQuestion {
  id: string;
  text: string;
  type: string;
  points: number;
  explanation: string | null;
  source_quote?: string | null;
  order_index: number;
  choices: QuizChoice[];
}

interface Quiz {
  id: string;
  lesson_id: string;
  title: string;
  pass_score: number;
  questions: QuizQuestion[];
}

interface GradedAnswer {
  question_id: string;
  selected_choice_ids: string[];
  correct_choice_ids: string[];
  is_correct: boolean;
  points_earned: number;
  points_possible: number;
}

interface PreviewResult {
  quiz_id: string;
  score_percent: number;
  total_points: number;
  earned_points: number;
  passed: boolean;
  graded_answers: GradedAnswer[];
}

function getChoiceClassName(selected: boolean, correct: boolean, reviewed: boolean) {
  if (correct) return 'border-success bg-success/10';
  if (selected && reviewed) return 'border-destructive bg-destructive/10';
  if (selected) return 'border-primary bg-primary/10';
  return 'border-border';
}

export default function QuizMethodologistPreviewPage() {
  const params = useParams();
  const quizId = params?.quizId as string;
  const searchParams = useSearchParams();
  const router = useRouter();
  const { t } = useT();
  const token = useAuthStore((state) => state.accessToken);
  const user = useAuthStore((state) => state.user);
  const initialized = useAuthStore((state) => state.initialized);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const courseId = searchParams.get('courseId');
  const lessonId = searchParams.get('lessonId');
  const canPreview = user?.role === 'methodologist' || user?.role === 'superadmin';

  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [result, setResult] = useState<PreviewResult | null>(null);

  const courseHref = courseId
    ? `/courses/${courseId}${lessonId ? `?lessonId=${encodeURIComponent(lessonId)}` : ''}`
    : getRoleHome(user?.role);

  const fetchQuiz = useCallback(async () => {
    if (!quizId || !token || !canPreview) return;
    setLoading(true);
    try {
      const response = await fetch(`${API_URL}/v1/quizzes/${quizId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || t('quiz.previewLoadFailed'));
      }
      setQuiz(await response.json());
    } catch (error) {
      toast.error(t('common.error'), {
        description: error instanceof Error ? error.message : t('quiz.previewLoadFailed'),
      });
    } finally {
      setLoading(false);
    }
  }, [API_URL, canPreview, quizId, t, token]);

  useEffect(() => {
    if (!initialized) return;
    if (!canPreview || !token || !quizId) {
      setLoading(false);
      return;
    }
    void fetchQuiz();
  }, [canPreview, fetchQuiz, initialized, quizId, token]);

  const gradedByQuestion = useMemo(
    () => new Map(result?.graded_answers.map((answer) => [answer.question_id, answer]) || []),
    [result],
  );

  const handleSelect = (question: QuizQuestion, choiceId: string) => {
    setAnswers((current) => {
      if (isSingleAnswerQuestionType(question.type)) {
        return { ...current, [question.id]: [choiceId] };
      }
      const selected = current[question.id] || [];
      return {
        ...current,
        [question.id]: selected.includes(choiceId)
          ? selected.filter((id) => id !== choiceId)
          : [...selected, choiceId],
      };
    });
  };

  const handleSubmit = async () => {
    if (!quiz || !token || submitting) return;
    if (quiz.questions.some((question) => !(answers[question.id]?.length))) {
      toast.error(t('quiz.previewCompleteAll'));
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetch(`${API_URL}/v1/quizzes/${quizId}/preview-submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          answers: quiz.questions.map((question) => ({
            question_id: question.id,
            selected_choice_ids: answers[question.id] || [],
          })),
          time_spent_seconds: 0,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || t('quiz.submissionFailedDescription'));
      }
      setResult(await response.json());
    } catch (error) {
      toast.error(t('common.saveFailed'), {
        description: error instanceof Error ? error.message : t('quiz.submissionFailedDescription'),
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetry = () => {
    setAnswers({});
    setResult(null);
  };

  if (!initialized || loading) return <WorkspacePage id="quiz-preview" title={t('quiz.previewTitle')}><WorkspacePanel aria-busy="true"><p role="status">{t('common.loading')}</p></WorkspacePanel></WorkspacePage>;

  if (!canPreview) {
    return (
      <WorkspacePage id="quiz-preview" className="mx-auto max-w-2xl" title={t('quiz.previewAccessDeniedTitle')}>
        <WorkspacePanel bodyClassName="space-y-4">
            <p className="text-sm text-muted-foreground">{t('quiz.previewAccessDenied')}</p>
            <Button onClick={() => router.replace(getRoleHome(user?.role))}>{t('nav.dashboard')}</Button>
        </WorkspacePanel>
      </WorkspacePage>
    );
  }

  if (!quiz) return <WorkspacePage id="quiz-preview" title={t('quiz.previewTitle')}><WorkspaceEmpty title={t('quiz.previewLoadFailed')} action={<Button onClick={() => void fetchQuiz()}>{t('common.retry')}</Button>} /></WorkspacePage>;

  return (
    <WorkspacePage id="quiz-preview" className="mx-auto max-w-4xl" title={t('quiz.previewTitle')} description={t('quiz.previewNotice')}>

        <WorkspaceToolbar className="items-center justify-between">
          <h2 className="min-w-0 break-words text-lg font-semibold">{quiz.title}</h2>
          <Link href={courseHref}><Button variant="outline">{t(courseId ? 'courses.backToCourse' : 'nav.dashboard')}</Button></Link>
        </WorkspaceToolbar>

        {result && (
          <Card className={result.passed ? 'border-success bg-success/10' : 'border-destructive bg-destructive/10'}>
            <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
              <div className="flex items-center gap-3">
                {result.passed
                  ? <CheckCircle2 className="h-8 w-8 text-success" aria-hidden="true" />
                  : <XCircle className="h-8 w-8 text-destructive" aria-hidden="true" />}
                <div>
                  <p className="font-semibold">{t(result.passed ? 'quiz.previewPassed' : 'quiz.previewFailed')}</p>
                  <p className="text-sm text-muted-foreground">
                    {t('quiz.previewScore', {
                      score: result.score_percent,
                      earned: result.earned_points,
                      total: result.total_points,
                    })}
                  </p>
                </div>
              </div>
              <Button variant="outline" onClick={handleRetry}>{t('quiz.previewRetry')}</Button>
            </CardContent>
          </Card>
        )}

        <div className="space-y-5">
          {quiz.questions.map((question, questionIndex) => {
            const graded = gradedByQuestion.get(question.id);
            return (
              <WorkspacePanel key={question.id} bodyClassName="space-y-5 sm:p-8">
                  <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-5">
                    <div>
                      <p className="text-xs text-muted-foreground">
                        {t('quiz.questionNumber', { current: questionIndex + 1, total: quiz.questions.length })}
                      </p>
                      <h3 className="mt-2 break-words text-lg font-semibold leading-7">{question.text}</h3>
                    </div>
                    {graded && (
                      <Badge variant={graded.is_correct ? 'default' : 'destructive'}>
                        {t(graded.is_correct ? 'quiz.answerCorrect' : 'quiz.answerIncorrect')}
                      </Badge>
                    )}
                  </div>

                  <div className="space-y-2">
                    {question.choices.map((choice) => {
                      const selected = (answers[question.id] || []).includes(choice.id);
                      const correct = graded?.correct_choice_ids.includes(choice.id) || false;
                      return (
                        <label
                          key={choice.id}
                          className={`flex min-h-12 flex-wrap items-start gap-3 rounded-xl border p-4 ${getChoiceClassName(
                            selected,
                            correct,
                            Boolean(graded),
                          )} ${result ? 'cursor-default' : 'cursor-pointer hover:bg-muted'}`}
                        >
                          <input
                            type={isSingleAnswerQuestionType(question.type) ? 'radio' : 'checkbox'}
                            name={`preview-${question.id}`}
                            checked={selected}
                            disabled={Boolean(result)}
                            onChange={() => handleSelect(question, choice.id)}
                            className="mt-1 shrink-0"
                          />
                          <span className="min-w-0 flex-1 break-words text-sm leading-6">
                            {choice.text}
                          </span>
                          {graded && selected && <Badge variant="outline">{t('quiz.selectedAnswer')}</Badge>}
                          {graded && correct && <Badge variant="outline">{t('quiz.correctAnswer')}</Badge>}
                        </label>
                      );
                    })}
                  </div>

                  {question.source_quote && (
                    <details className="rounded-lg bg-muted p-3 text-sm">
                      <summary className="cursor-pointer font-medium">{t('quiz.sourceQuoteForReview')}</summary>
                      <p className="mt-2 whitespace-pre-wrap">{question.source_quote}</p>
                    </details>
                  )}

                  {graded && question.explanation && (
                    <div className="rounded-lg bg-muted p-3 text-sm">
                      <span className="font-medium">{t('quiz.explanation')}:</span> {question.explanation}
                    </div>
                  )}
              </WorkspacePanel>
            );
          })}
        </div>

        {!result && (
          <WorkspaceToolbar className="justify-end">
            <Button onClick={handleSubmit} disabled={submitting || quiz.questions.length === 0}>
              {submitting ? t('quiz.submitting') : t('quiz.previewFinish')}
            </Button>
          </WorkspaceToolbar>
        )}
    </WorkspacePage>
  );
}
