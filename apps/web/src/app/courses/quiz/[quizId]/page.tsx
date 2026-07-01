'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams } from 'next/navigation';
import { Card, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { toast } from '@/components/ui/Toast';
import { CheckCircle2, XCircle, Circle, Lightbulb } from 'lucide-react';

interface QuizChoice {
  id: string;
  text: string;
  order_index: number;
}

interface Question {
  id: string;
  text: string;
  type: string;
  points: number;
  explanation: string | null;
  order_index: number;
  choices: QuizChoice[];
}

interface Quiz {
  id: string;
  lesson_id: string;
  title: string;
  pass_score: number;
  time_limit: number | null;
  attempt_limit: number;
  questions: Question[];
}

interface GradedAnswer {
  question_id: string;
  selected_choice_ids: string[];
  correct_choice_ids: string[];
  is_correct: boolean;
  points_earned: number;
  points_possible: number;
}

interface QuizResult {
  attempt: {
    id: string;
    quiz_id: string;
    user_id: string;
    score_percent: number;
    total_points: number;
    earned_points: number;
    passed: boolean;
    answers: GradedAnswer[];
    started_at: string;
    completed_at: string | null;
    time_spent_seconds: number | null;
  };
  correct_answers: number;
  total_questions: number;
  passed: boolean;
  message: string;
}

interface QuizAttempt {
  id: string;
  score_percent: number;
  passed: boolean;
  started_at: string;
  completed_at: string | null;
}

function getRoleHome(role?: string | null) {
  return role === 'student' ? '/student' : '/dashboard';
}

export default function QuizPlayerPage() {
  const params = useParams();
  const quizId = params?.quizId as string;
  const { t } = useT();
  const token = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentIdx, setCurrentIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [attempts, setAttempts] = useState<QuizAttempt[]>([]);
  const [showReview, setShowReview] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const fetchQuiz = useCallback(async () => {
    if (!quizId || !token) return;
    try {
      const [quizRes, attemptsRes] = await Promise.all([
        fetch(`${API_URL}/v1/quizzes/${quizId}`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/v1/quizzes/${quizId}/attempts`, { headers: { Authorization: `Bearer ${token}` } }),
      ]);
      if (quizRes.ok) {
        const data = await quizRes.json();
        setQuiz(data);
        if (data.time_limit) setTimeLeft(data.time_limit * 60);
      }
      if (attemptsRes.ok) setAttempts(await attemptsRes.json());
    } finally {
      setLoading(false);
    }
  }, [quizId, token, API_URL]);

  useEffect(() => {
    fetchQuiz();
  }, [fetchQuiz]);

  // Timer
  useEffect(() => {
    if (timeLeft === null || timeLeft <= 0 || result) return;
    timerRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev !== null && prev <= 1) {
          handleSubmit();
          return 0;
        }
        return prev !== null ? prev - 1 : null;
      });
    }, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [timeLeft !== null && !result]);

  const handleSelect = (questionId: string, choiceId: string, type: string) => {
    setAnswers((prev) => {
      if (type === 'MCQ' || type === 'true_false') {
        return { ...prev, [questionId]: [choiceId] };
      }
      // Multi-select for matching/other types
      const current = prev[questionId] || [];
      const next = current.includes(choiceId) ? current.filter((id) => id !== choiceId) : [...current, choiceId];
      return { ...prev, [questionId]: next };
    });
  };

  const handleSubmit = async () => {
    if (!quizId || !token || submitting || result) return;
    setSubmitting(true);
    try {
      const submission = {
        answers: quiz?.questions.map((q) => ({
          question_id: q.id,
          selected_choice_ids: answers[q.id] || [],
        })) || [],
        time_spent_seconds: quiz?.time_limit ? (quiz.time_limit * 60 - (timeLeft || 0)) : undefined,
      };
      const res = await fetch(`${API_URL}/v1/quizzes/${quizId}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(submission),
      });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
        setShowReview(true);
        if (timerRef.current) clearInterval(timerRef.current);
        // Refresh attempts
        const attemptsRes = await fetch(`${API_URL}/v1/quizzes/${quizId}/attempts`, { headers: { Authorization: `Bearer ${token}` } });
        if (attemptsRes.ok) setAttempts(await attemptsRes.json());
        toast.success(data.passed ? 'Тест пройден!' : 'Тест завершён', {
          description: `Результат: ${data.score_percent ?? 0}%`,
        });
      } else {
        const err = await res.json();
        toast.error(t('common.saveFailed'), { description: err.detail || 'Ошибка отправки' });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRetry = () => {
    setQuiz(null);
    setResult(null);
    setAnswers({});
    setCurrentIdx(0);
    setShowReview(false);
    setLoading(true);
    fetchQuiz();
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  if (loading) return <div className="p-6">{t('common.loading')}</div>;
  if (!quiz) return <div className="p-6">{t('common.error')}: Quiz not found</div>;

  const currentQ = quiz.questions[currentIdx];
  const totalQuestions = quiz.questions.length;
  const answeredCount = Object.keys(answers).length;
  const attemptsUsed = attempts.length;
  const canAttempt = attemptsUsed < quiz.attempt_limit;
  const gradedAnswers = result?.attempt.answers || [];

  return (
    <div className="min-h-screen bg-muted">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">{quiz.title}</h1>
          <div className="flex items-center gap-4">
            {timeLeft !== null && !result && (
              <div
                role="timer"
                aria-live={timeLeft < 60 ? 'assertive' : 'polite'}
                aria-atomic="true"
                aria-label={t('quiz.timeLeft') || 'Time left'}
                className={
                  'text-lg px-3 py-1 rounded-md font-mono ' +
                  (timeLeft < 60
                    ? 'bg-destructive/15 text-destructive'
                    : 'bg-muted text-foreground')
                }
              >
                {formatTime(timeLeft)}
              </div>
            )}
            {result && (
              <Badge variant={result.passed ? 'default' : 'destructive'} className="text-lg px-3 py-1">
                {result.attempt.score_percent}%
              </Badge>
            )}
          </div>
        </div>

        {/* Results Summary */}
        {result && (
          <Card className={result.passed ? 'border-success bg-success/10' : 'border-destructive bg-destructive/10'}>
            <CardContent className="p-6 text-center space-y-3">
              <div className={`${result.passed ? 'text-success' : 'text-destructive'}`}>
                {result.passed ? <CheckCircle2 className="w-12 h-12 mx-auto" /> : <XCircle className="w-12 h-12 mx-auto" />}
              </div>
              <p className="text-lg font-semibold">{result.message}</p>
              <p className="text-sm text-muted-foreground">
                {result.correct_answers} / {result.total_questions} {t('quiz.correct')} · {result.attempt.score_percent}%
              </p>
              <div className="flex gap-3 justify-center mt-4">
                <Button variant="outline" onClick={() => setShowReview(!showReview)}>
                  {showReview ? t('quiz.hideReview') : t('quiz.showReview')}
                </Button>
                {canAttempt && !result.passed && (
                  <Button onClick={handleRetry}>{t('quiz.tryAgain')}</Button>
                )}
                <a href={getRoleHome(user?.role)}>
                  <Button variant="outline">{t('nav.dashboard')}</Button>
                </a>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Question Navigation */}
        {!result && (
          <div className="flex flex-wrap gap-2">
            {quiz.questions.map((q, i) => {
              const selected = answers[q.id]?.length > 0;
              return (
                <button
                  key={q.id}
                  onClick={() => setCurrentIdx(i)}
                  className={`w-9 h-9 rounded-full text-sm font-medium border transition-colors ${
                    i === currentIdx
                      ? 'bg-primary text-white border-primary'
                      : selected
                      ? 'bg-primary/15 text-primary border-primary/40'
                      : 'bg-card text-foreground border-border hover:border-primary/70'
                  }`}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>
        )}

        {/* Question Display */}
        {currentQ && !showReview && (
          <Card>
            <CardContent className="p-6 space-y-4">
              <div className="flex items-start gap-2">
                <span className="text-sm text-muted-foreground shrink-0">
                  {currentIdx + 1}/{totalQuestions}
                </span>
                <p className="font-medium">{currentQ.text}</p>
              </div>
              <p className="text-xs text-muted-foreground">
                {t('quiz.points')}: {currentQ.points} · {currentQ.type}
              </p>
              <div className="space-y-2">
                {currentQ.choices.map((choice) => {
                  const isSelected = (answers[currentQ.id] || []).includes(choice.id);
                  return (
                    <label
                      key={choice.id}
                      className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                        isSelected ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'
                      }`}
                    >
                      <input
                        type={currentQ.type === 'MCQ' ? 'radio' : 'checkbox'}
                        name={`q-${currentQ.id}`}
                        checked={isSelected}
                        onChange={() => handleSelect(currentQ.id, choice.id, currentQ.type)}
                        className="shrink-0"
                      />
                      <span>{choice.text}</span>
                    </label>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Review Mode — show all questions with correct/incorrect */}
        {showReview && result && (
          <div className="space-y-4">
            <h2 className="text-lg font-semibold">{t('quiz.review')}</h2>
            {quiz.questions.map((q, i) => {
              const graded = gradedAnswers.find((a) => a.question_id === q.id);
              const isCorrect = graded?.is_correct ?? false;
              return (
                <Card key={q.id} className={isCorrect ? 'border-success/40' : 'border-destructive/40'}>
                  <CardContent className="p-4 space-y-3">
                    <div className="flex items-start gap-2">
                      <span className={`shrink-0 ${isCorrect ? 'text-success' : 'text-destructive'}`}>
                        {isCorrect ? <CheckCircle2 className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
                      </span>
                      <div>
                        <p className="font-medium">{i + 1}. {q.text}</p>
                        <p className="text-xs text-muted-foreground">{q.points} {t('quiz.points')}</p>
                      </div>
                    </div>
                    <div className="space-y-1 ml-8">
                      {q.choices.map((c) => {
                        const wasSelected = graded?.selected_choice_ids.includes(c.id) ?? false;
                        const isCorrectChoice = graded?.correct_choice_ids.includes(c.id) ?? false;
                        return (
                          <div key={c.id} className={`flex items-center gap-2 text-sm py-1 px-2 rounded ${
                            isCorrectChoice ? 'bg-success/15 text-success' : wasSelected ? 'bg-destructive/15 text-destructive' : 'text-muted-foreground'
                          }`}>
                            <span>
                              {isCorrectChoice ? <CheckCircle2 className="w-4 h-4" /> : wasSelected ? <XCircle className="w-4 h-4" /> : <Circle className="w-4 h-4" />}
                            </span>
                            <span>{c.text}</span>
                          </div>
                        );
                      })}
                    </div>
                    {q.explanation && (
                      <div className="ml-8 mt-2 flex items-center gap-2 p-3 bg-primary/10 text-sm text-primary rounded">
                        <Lightbulb className="w-4 h-4 shrink-0" /> {q.explanation}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}

        {/* Submit / Navigation */}
        {!result && (
          <div className="flex items-center justify-between">
            <Button
              variant="outline"
              onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
              disabled={currentIdx === 0}
            >
              {t('quiz.previous')}
            </Button>
            <span className="text-sm text-muted-foreground">
              {answeredCount}/{totalQuestions}
            </span>
            {currentIdx < totalQuestions - 1 ? (
              <Button onClick={() => setCurrentIdx((i) => Math.min(totalQuestions - 1, i + 1))}>
                {t('quiz.next')}
              </Button>
            ) : (
              <Button
                onClick={handleSubmit}
                disabled={submitting || answeredCount === 0}
              >
                {submitting ? t('quiz.submitting') : t('quiz.finish')}
              </Button>
            )}
          </div>
        )}

        {/* Previous Attempts */}
        {!result && attempts.length > 0 && (
          <Card>
            <CardContent className="p-4">
              <h3 className="font-medium mb-2">{t('quiz.attempts')} ({attemptsUsed}/{quiz.attempt_limit})</h3>
              <div className="space-y-1">
                {attempts.map((a) => (
                  <div key={a.id} className="flex items-center gap-3 text-sm">
                    <Badge variant={a.passed ? 'default' : 'outline'}>
                      {a.score_percent}%
                    </Badge>
                    <span className={`flex items-center gap-1 ${a.passed ? 'text-success' : 'text-destructive'}`}>
                      {a.passed ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                    </span>
                    <span className="text-muted-foreground">
                      {new Date(a.started_at).toLocaleDateString('ru-RU')}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
