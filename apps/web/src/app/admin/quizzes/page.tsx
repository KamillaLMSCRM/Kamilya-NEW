'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, Button, Badge, Input } from '@/components/ui';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import { toast } from '@/components/ui/Toast';
import { CheckCircle2, Circle, Lightbulb } from 'lucide-react';

interface QuizChoice {
  id: string;
  text: string;
  is_correct: boolean;
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

export default function QuizzesAdminPage() {
  const { t } = useT();
    const { confirm, dialog } = useConfirm();
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedQuiz, setSelectedQuiz] = useState<Quiz | null>(null);
  const [editing, setEditing] = useState(false);
  const [newQuiz, setNewQuiz] = useState({ lesson_id: '', title: '', pass_score: 80, time_limit: '', attempt_limit: 3 });
  const [newQuestion, setNewQuestion] = useState({ text: '', type: 'MCQ', points: 1, explanation: '' });
  const [newChoices, setNewChoices] = useState<Array<{ text: string; is_correct: boolean }>>([
    { text: '', is_correct: false },
    { text: '', is_correct: false },
    { text: '', is_correct: false },
    { text: '', is_correct: false },
  ]);
  const [showCreateQuiz, setShowCreateQuiz] = useState(false);
  const [showAddQuestion, setShowAddQuestion] = useState(false);
  const token = useAuthStore((s) => s.accessToken);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;

  const fetchQuizzes = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API_URL}/v1/quizzes`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setQuizzes(await res.json());
    } finally {
      setLoading(false);
    }
  }, [token, API_URL]);

  useEffect(() => { fetchQuizzes(); }, [fetchQuizzes]);

  const handleCreateQuiz = async () => {
    if (!token || !newQuiz.lesson_id || !newQuiz.title) return;
    const res = await fetch(`${API_URL}/v1/quizzes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        lesson_id: newQuiz.lesson_id,
        title: newQuiz.title,
        pass_score: newQuiz.pass_score,
        time_limit: newQuiz.time_limit ? parseInt(newQuiz.time_limit) : null,
        attempt_limit: newQuiz.attempt_limit,
      }),
    });
    if (res.ok) {
      const quiz = await res.json();
      setQuizzes((prev) => [...prev, quiz]);
      setSelectedQuiz(quiz);
      setShowCreateQuiz(false);
      setNewQuiz({ lesson_id: '', title: '', pass_score: 80, time_limit: '', attempt_limit: 3 });
    }
  };

  const handleAddQuestion = async () => {
    if (!token || !selectedQuiz || !newQuestion.text) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${selectedQuiz.id}/questions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        ...newQuestion,
        order_index: selectedQuiz.questions.length,
        choices: newChoices.filter((c) => c.text.trim()).map((c, i) => ({
          text: c.text,
          is_correct: c.is_correct,
          order_index: i,
        })),
      }),
    });
    if (res.ok) {
      const quiz = await res.json();
      setSelectedQuiz(quiz);
      setShowAddQuestion(false);
      setNewQuestion({ text: '', type: 'MCQ', points: 1, explanation: '' });
      setNewChoices([
        { text: '', is_correct: false },
        { text: '', is_correct: false },
        { text: '', is_correct: false },
        { text: '', is_correct: false },
      ]);
    }
  };

  const handleDeleteQuestion = async (questionId: string) => {
        if (!token || !selectedQuiz) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteQuestion'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${selectedQuiz.id}/questions/${questionId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const quiz = await res.json();
      setSelectedQuiz(quiz);
    }
  };

  const handleDeleteQuiz = async (quizId: string) => {
        if (!token) return;
    const ok = await confirm({
      title: t('dialogs.confirmDeleteQuiz'),
      variant: 'danger',
      confirmLabel: t('dialogs.delete'),
    });
    if (!ok) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${quizId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      setQuizzes((prev) => prev.filter((q) => q.id !== quizId));
      setSelectedQuiz(null);
    }
  };

  const handleLoadQuiz = async (quizId: string) => {
    if (!token) return;
    const res = await fetch(`${API_URL}/v1/quizzes/${quizId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) setSelectedQuiz(await res.json());
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">{t('quiz.title')} — Админ</h1>
        <Button onClick={() => setShowCreateQuiz(!showCreateQuiz)}>
          {t('common.create')} {t('quiz.title')}
        </Button>
      </div>

      {/* Create Quiz Form */}
      {showCreateQuiz && (
        <Card>
          <CardContent className="p-4 space-y-3">
            <h3 className="font-semibold">{t('common.create')} {t('quiz.title')}</h3>
            <Input
              placeholder="Lesson ID (UUID)"
              value={newQuiz.lesson_id}
              onChange={(e) => setNewQuiz((p) => ({ ...p, lesson_id: e.target.value }))}
            />
            <Input
              placeholder={t('courses.courseTitle')}
              value={newQuiz.title}
              onChange={(e) => setNewQuiz((p) => ({ ...p, title: e.target.value }))}
            />
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-sm text-gray-500">{t('quiz.passScore')}</label>
                <Input
                  type="number"
                  value={newQuiz.pass_score}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, pass_score: parseInt(e.target.value) || 80 }))}
                />
              </div>
              <div>
                <label className="text-sm text-gray-500">{t('quiz.timeLeft')} (мин)</label>
                <Input
                  type="number"
                  placeholder="∞"
                  value={newQuiz.time_limit}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, time_limit: e.target.value }))}
                />
              </div>
              <div>
                <label className="text-sm text-gray-500">Лимит попыток</label>
                <Input
                  type="number"
                  value={newQuiz.attempt_limit}
                  onChange={(e) => setNewQuiz((p) => ({ ...p, attempt_limit: parseInt(e.target.value) || 3 }))}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={handleCreateQuiz}>{t('common.create')}</Button>
              <Button variant="outline" onClick={() => setShowCreateQuiz(false)}>{t('common.cancel')}</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Quiz list / load */}
        <Card>
          <CardContent className="p-4 space-y-3">
            <h3 className="font-semibold">Загрузить тест по ID</h3>
            <div className="flex gap-2">
              <Input
                placeholder="Quiz ID (UUID)"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleLoadQuiz((e.target as HTMLInputElement).value);
                }}
              />
              <Button variant="outline" onClick={(e) => {
                const input = (e.target as HTMLElement).closest('.flex')?.querySelector('input');
                if (input?.value) handleLoadQuiz(input.value);
              }}>
                Загрузить
              </Button>
            </div>
            {quizzes.length > 0 && (
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {quizzes.map((q) => (
                  <div
                    key={q.id}
                    className={`p-2 rounded cursor-pointer text-sm ${selectedQuiz?.id === q.id ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
                    onClick={() => setSelectedQuiz(q)}
                  >
                    {q.title}
                    <Badge className="ml-2">{q.questions.length}</Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Selected Quiz */}
        {selectedQuiz ? (
          <div className="lg:col-span-2 space-y-4">
            <Card>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-lg">{selectedQuiz.title}</h3>
                  <div className="flex gap-2">
                    <Button variant="destructive" size="sm" onClick={() => handleDeleteQuiz(selectedQuiz.id)}>
                      {t('common.delete')}
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>{t('quiz.passScore')}: <strong>{selectedQuiz.pass_score}%</strong></div>
                  <div>{t('quiz.timeLeft')}: <strong>{selectedQuiz.time_limit ? `${selectedQuiz.time_limit} мин` : '∞'}</strong></div>
                  <div>Попыток: <strong>{selectedQuiz.attempt_limit}</strong></div>
                </div>
                <div className="text-sm text-gray-500">
                  {selectedQuiz.questions.length} вопросов · {selectedQuiz.questions.reduce((a, q) => a + q.points, 0)} баллов
                </div>
              </CardContent>
            </Card>

            {/* Questions */}
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="font-semibold">Вопросы</h4>
                <Button size="sm" onClick={() => setShowAddQuestion(!showAddQuestion)}>
                  + {t('common.create')} вопрос
                </Button>
              </div>

              {showAddQuestion && (
                <Card className="border-blue-200">
                  <CardContent className="p-4 space-y-3">
                    <Input
                      placeholder="Текст вопроса"
                      value={newQuestion.text}
                      onChange={(e) => setNewQuestion((p) => ({ ...p, text: e.target.value }))}
                    />
                    <div className="grid grid-cols-3 gap-3">
                      <select
                        value={newQuestion.type}
                        onChange={(e) => setNewQuestion((p) => ({ ...p, type: e.target.value }))}
                        className="border rounded px-2 py-1 text-sm"
                      >
                        <option value="MCQ">MCQ (выбор)</option>
                        <option value="true_false">True/False</option>
                        <option value="matching">Matching</option>
                      </select>
                      <Input
                        type="number"
                        placeholder="Баллы"
                        value={newQuestion.points}
                        onChange={(e) => setNewQuestion((p) => ({ ...p, points: parseInt(e.target.value) || 1 }))}
                      />
                    </div>
                    <Input
                      placeholder="Объяснение (опционально)"
                      value={newQuestion.explanation}
                      onChange={(e) => setNewQuestion((p) => ({ ...p, explanation: e.target.value }))}
                    />
                    <div className="space-y-2">
                      <p className="text-sm font-medium">Варианты ответов:</p>
                      {newChoices.map((c, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <input
                            type="radio"
                            name="correct-choice"
                            checked={c.is_correct}
                            onChange={() => {
                              setNewChoices((prev) => prev.map((ch, j) => ({ ...ch, is_correct: j === i })));
                            }}
                          />
                          <Input
                            placeholder={`Вариант ${i + 1}`}
                            value={c.text}
                            onChange={(e) => {
                              setNewChoices((prev) => prev.map((ch, j) => j === i ? { ...ch, text: e.target.value } : ch));
                            }}
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex gap-2">
                      <Button onClick={handleAddQuestion}>{t('common.create')}</Button>
                      <Button variant="outline" onClick={() => setShowAddQuestion(false)}>{t('common.cancel')}</Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {selectedQuiz.questions.map((q, i) => (
                <Card key={q.id}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <Badge variant="outline">{i + 1}</Badge>
                          <span className="font-medium">{q.text}</span>
                          <Badge>{q.points} {t('quiz.points')}</Badge>
                          <Badge variant="outline">{q.type}</Badge>
                        </div>
                        <div className="ml-8 space-y-1">
                          {q.choices.map((c) => (
                            <div key={c.id} className={`flex items-center gap-1 text-sm ${c.is_correct ? 'text-green-600 font-medium' : 'text-gray-600'}`}>
                              {c.is_correct ? <CheckCircle2 className="w-4 h-4" /> : <Circle className="w-4 h-4" />} {c.text}
                            </div>
                          ))}
                        </div>
                        {q.explanation && (
                          <div className="ml-8 mt-2 flex items-center gap-1 text-xs text-blue-600">
                            <Lightbulb className="w-4 h-4" /> {q.explanation}
                          </div>
                        )}
                      </div>
                      <Button variant="destructive" size="sm" onClick={() => handleDeleteQuestion(q.id)}>
                        {t('common.delete')}
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ) : (
          <Card className="lg:col-span-2">
            <CardContent className="p-8 text-center text-gray-400">
              Загрузите тест по ID или создайте новый
            </CardContent>
          </Card>
        )}
      </div>
{dialog}
    </div>
  );
}
