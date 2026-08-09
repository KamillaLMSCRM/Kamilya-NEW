'use client';

import { FormEvent, useState } from 'react';
import { useParams } from 'next/navigation';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
type Question = { id: string; text: string; type: string; choices: { id: string; text: string }[] };
type Exchange = { access_token: string; attempt_id: string; title: string; instructions: string; assessment: { quizzes: { questions: Question[] }[] } };

export default function CandidateAssessmentPage() {
  const { token } = useParams<{ token: string }>();
  const [pin, setPin] = useState('');
  const [consent, setConsent] = useState(false);
  const [session, setSession] = useState<Exchange | null>(null);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [result, setResult] = useState<{ score_percent: number; passed: boolean } | null>(null);
  const [error, setError] = useState('');

  async function open(event: FormEvent) {
    event.preventDefault(); setError('');
    const response = await fetch(`${API}/v1/candidate-assessment/${encodeURIComponent(token)}/exchange`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin, consent }) });
    if (!response.ok) { setError('Ссылка или PIN недействительны.'); return; }
    setSession(await response.json());
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!session) return; setError('');
    const response = await fetch(`${API}/v1/candidate-assessment/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` }, body: JSON.stringify({ attempt_id: session.attempt_id, answers: Object.entries(answers).map(([question_id, choices]) => ({ question_id, selected_choice_ids: choices })) }) });
    if (!response.ok) { setError('Не удалось отправить оценку.'); return; }
    setResult(await response.json());
  }
  if (result) return <main className="flex min-h-screen items-center justify-center p-4"><Card className="w-full max-w-lg"><CardContent className="space-y-2 p-6 text-center"><h1 className="text-2xl font-bold">Оценка завершена</h1><p>Результат: {result.score_percent}%</p><p className="text-sm text-muted-foreground">Решение о найме принимает организация отдельно.</p></CardContent></Card></main>;
  if (!session) return <main className="flex min-h-screen items-center justify-center p-4"><Card className="w-full max-w-md"><CardHeader><CardTitle>Оценка кандидата</CardTitle></CardHeader><CardContent><form className="space-y-4" onSubmit={open}><Input aria-label="PIN" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" /><label className="flex gap-2 text-sm"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />Я согласен(на) на обработку данных для оценки</label><Button className="w-full" disabled={pin.length !== 6 || !consent}>Открыть оценку</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}</form></CardContent></Card></main>;
  const questions = session.assessment.quizzes.flatMap((quiz) => quiz.questions);
  return <main className="mx-auto max-w-3xl space-y-5 p-4 sm:p-8"><div><h1 className="text-2xl font-bold">{session.title}</h1><p className="text-sm text-muted-foreground">{session.instructions}</p></div><form className="space-y-4" onSubmit={submit}>{questions.map((question, index) => <Card key={question.id}><CardContent className="space-y-3 p-5"><p className="font-medium">{index + 1}. {question.text}</p>{question.choices.map((choice) => { const multiple = question.type === 'multiple_choice'; const selected = answers[question.id] || []; return <label key={choice.id} className="flex gap-2 text-sm"><input type={multiple ? 'checkbox' : 'radio'} name={question.id} value={choice.id} checked={selected.includes(choice.id)} onChange={() => setAnswers((current) => ({ ...current, [question.id]: multiple ? (selected.includes(choice.id) ? selected.filter((id) => id !== choice.id) : [...selected, choice.id]) : [choice.id] }))} />{choice.text}</label>; })}</CardContent></Card>)}<Button className="w-full" disabled={questions.some((question) => !(answers[question.id]?.length))}>Отправить ответы</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}</form></main>;
}
