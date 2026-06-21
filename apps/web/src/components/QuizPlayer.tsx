'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardHeader, CardTitle, CardContent, Button, Badge } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';

interface Choice {
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
  choices: Choice[];
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

interface QuizResult {
  attempt: {
    id: string;
    score_percent: number;
    passed: boolean;
  };
  correct_answers: number;
  total_questions: number;
  passed: boolean;
  message: string;
}

interface QuizPlayerProps {
  quizId: string;
  onComplete?: (result: QuizResult) => void;
}

export default function QuizPlayer({ quizId, onComplete }: QuizPlayerProps) {
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<QuizResult | null>(null);
  const [timeLeft, setTimeLeft] = useState<number | null>(null);
  const [startTime] = useState(Date.now());
  const token = useAuthStore((s) => s.token);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  useEffect(() => {
    if (quizId) fetchQuiz();
  }, [quizId]);

  useEffect(() => {
    if (quiz?.time_limit && !result) {
      setTimeLeft(quiz.time_limit * 60);
      const timer = setInterval(() => {
        setTimeLeft((prev) => {
          if (prev !== null && prev <= 1) {
            clearInterval(timer);
            handleSubmit();
            return 0;
          }
          return prev !== null ? prev - 1 : null;
        });
      }, 1000);
      return () => clearInterval(timer);
    }
  }, [quiz?.time_limit, result]);

  const fetchQuiz = async () => {
    const res = await fetch(`${API_URL}/v1/quizzes/${quizId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) setQuiz(await res.json());
  };

  const handleAnswer = (questionId: string, choiceId: string, multiple: boolean) => {
    setAnswers((prev) => {
      if (multiple) {
        const current = prev[questionId] || [];
        const updated = current.includes(choiceId)
          ? current.filter((id) => id !== choiceId)
          : [...current, choiceId];
        return { ...prev, [questionId]: updated };
      }
      return { ...prev, [questionId]: [choiceId] };
    });
  };

  const handleSubmit = async () => {
    if (submitting || result) return;
    setSubmitting(true);

    const timeSpent = Math.floor((Date.now() - startTime) / 1000);
    const submission = {
      answers: Object.entries(answers).map(([questionId, selectedChoiceIds]) => ({
        question_id: questionId,
        selected_choice_ids: selectedChoiceIds,
      })),
      time_spent_seconds: timeSpent,
    };

    const res = await fetch(`${API_URL}/v1/quizzes/${quizId}/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(submission),
    });

    if (res.ok) {
      const data = await res.json();
      setResult(data);
      onComplete?.(data);
    }
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  if (!quiz) return <div className="p-6">Загрузка теста...</div>;

  if (result) {
    return (
      <Card className="max-w-2xl mx-auto">
        <CardHeader>
          <CardTitle>{result.passed ? 'Тест пройден!' : 'Тест не пройден'}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-center">
            <div className="text-6xl font-bold text-blue-600">{result.attempt.score_percent}%</div>
            <p className="text-gray-500 mt-2">{result.message}</p>
          </div>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold">{result.correct_answers}</div>
              <div className="text-sm text-gray-500">Правильных</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{result.total_questions}</div>
              <div className="text-sm text-gray-500">Всего</div>
            </div>
            <div>
              <div className="text-2xl font-bold">{quiz.pass_score}%</div>
              <div className="text-sm text-gray-500">Проходной</div>
            </div>
          </div>
          {!result.passed && (
            <Button onClick={() => { setResult(null); setCurrentQuestion(0); setAnswers({}); }} className="w-full">
              Попробовать снова
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  const question = quiz.questions[currentQuestion];
  const isMultiple = question.type === 'multiple_choice';
  const progress = ((currentQuestion + 1) / quiz.questions.length) * 100;

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">{quiz.title}</h2>
        {timeLeft !== null && (
          <Badge variant={timeLeft < 60 ? 'destructive' : 'default'}>
            {formatTime(timeLeft)}
          </Badge>
        )}
      </div>

      <div className="h-2 bg-gray-200 rounded">
        <div className="h-2 bg-blue-600 rounded transition-all" style={{ width: `${progress}%` }} />
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="mb-4">
            <span className="text-sm text-gray-500">
              Вопрос {currentQuestion + 1} из {quiz.questions.length}
            </span>
            <span className="text-sm text-gray-400 ml-2">({question.points} балл)</span>
          </div>

          <p className="text-lg font-medium mb-4">{question.text}</p>

          <div className="space-y-2">
            {question.choices.map((choice) => {
              const selected = answers[question.id]?.includes(choice.id);
              return (
                <button
                  key={choice.id}
                  onClick={() => handleAnswer(question.id, choice.id, isMultiple)}
                  className={`w-full text-left p-3 rounded border transition-colors ${
                    selected
                      ? 'border-blue-500 bg-blue-50'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-4 h-4 rounded-${isMultiple ? 'md' : 'full'} border flex items-center justify-center ${
                      selected ? 'border-blue-500 bg-blue-500' : 'border-gray-300'
                    }`}>
                      {selected && <span className="text-white text-xs">✓</span>}
                    </div>
                    {choice.text}
                  </div>
                </button>
              );
            })}
          </div>

          <div className="flex justify-between mt-6">
            <Button
              variant="outline"
              onClick={() => setCurrentQuestion((p) => Math.max(0, p - 1))}
              disabled={currentQuestion === 0}
            >
              Назад
            </Button>
            {currentQuestion < quiz.questions.length - 1 ? (
              <Button onClick={() => setCurrentQuestion((p) => p + 1)}>
                Далее
              </Button>
            ) : (
              <Button onClick={handleSubmit} disabled={submitting}>
                {submitting ? 'Проверка...' : 'Завершить тест'}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
