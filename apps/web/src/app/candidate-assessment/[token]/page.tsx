'use client';

import { FormEvent, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Button, Input } from '@/components/ui';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PublicWorkspace, WorkspaceEmpty, WorkspacePanel } from '@/features/workspace-design';
import { getPublicWorkspaceCopy } from '@/features/workspace-design/publicCopy';
import { useT } from '@/i18n/useT';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
type Question = { id: string; text: string; type: string; choices: { id: string; text: string }[] };
type Exchange = { access_token: string; attempt_id: string; title: string; instructions: string; assessment: { quizzes: { questions: Question[] }[] } };

export default function CandidateAssessmentPage() {
  const { token } = useParams<{ token: string }>();
  const { lang } = useT();
  const copy = getPublicWorkspaceCopy(lang);
  const [pin, setPin] = useState('');
  const [consent, setConsent] = useState(false);
  const [session, setSession] = useState<Exchange | null>(null);
  const [answers, setAnswers] = useState<Record<string, string[]>>({});
  const [result, setResult] = useState<{ score_percent: number; passed: boolean } | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function open(event: FormEvent) {
    event.preventDefault(); if (busy || pin.length !== 6 || !consent) return; setError(''); setBusy(true);
    try {
      const response = await fetch(`${API}/v1/candidate-assessment/${encodeURIComponent(token)}/exchange`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin, consent }) });
      if (!response.ok) { setError(copy.candidateInvalid); return; }
      setSession(await response.json());
    } catch { setError(copy.candidateInvalid); }
    finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!session || busy) return; setError(''); setBusy(true);
    try {
      const response = await fetch(`${API}/v1/candidate-assessment/submit`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` }, body: JSON.stringify({ attempt_id: session.attempt_id, answers: Object.entries(answers).map(([question_id, choices]) => ({ question_id, selected_choice_ids: choices })) }) });
      if (!response.ok) { setError(copy.candidateSubmitFailed); return; }
      setResult(await response.json());
    } catch { setError(copy.candidateSubmitFailed); }
    finally { setBusy(false); }
  }
  if (result) return <PublicWorkspace id="candidate-assessment" title={copy.candidateDone} description={copy.hiringHint} actions={<LanguageSwitcher />}>
    <div role="status" className="mx-auto max-w-xl"><WorkspacePanel><p className="text-center text-3xl font-semibold leading-tight tabular-nums">{copy.result}: {result.score_percent}%</p></WorkspacePanel></div><PublicLegalFooter />
  </PublicWorkspace>;
  if (!session) return <PublicWorkspace id="candidate-assessment" title={copy.candidateTitle} description={copy.candidateHint} actions={<LanguageSwitcher />}>
    <div className="mx-auto w-full max-w-lg"><WorkspacePanel title={copy.confirmationStep}>
      <form className="space-y-5" onSubmit={open}>
        <label className="block space-y-2 text-sm font-medium">PIN<Input aria-label="PIN" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" className="h-12 text-center text-xl tracking-[0.3em]" /></label>
        <label htmlFor="candidate-privacy-consent" className="flex items-start gap-3 rounded-xl border border-border bg-muted/30 p-4 text-sm leading-6"><input id="candidate-privacy-consent" className="mt-1.5 shrink-0" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /><span>{copy.consentPrefix} <Link href="/legal/privacy" className="text-primary underline">{copy.privacyLink}</Link></span></label>
        <Button className="min-h-11 w-full" disabled={busy || pin.length !== 6 || !consent}>{busy ? copy.checking : copy.openAssessment}</Button>
        {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm leading-6 text-destructive">{error}</p>}
      </form>
    </WorkspacePanel></div><PublicLegalFooter />
  </PublicWorkspace>;
  const questions = session.assessment.quizzes.flatMap((quiz) => quiz.questions);
  return <PublicWorkspace id="candidate-assessment" title={session.title} description={session.instructions} actions={<LanguageSwitcher />}>
    {questions.length === 0 ? <WorkspaceEmpty title={copy.assessmentEmpty} description={copy.assessmentEmptyHint} /> : <form className="mx-auto max-w-3xl space-y-5" onSubmit={submit}>
      {questions.map((question, index) => <WorkspacePanel key={question.id}>
        <fieldset className="min-w-0 space-y-3" disabled={busy}><legend className="mb-4 text-lg font-semibold leading-7">{index + 1}. {question.text}</legend>
          {question.choices.map((choice) => { const multiple = question.type === 'multiple_choice'; const selected = answers[question.id] || []; return <label key={choice.id} className={`flex min-h-12 cursor-pointer items-start gap-3 rounded-xl border p-4 text-sm leading-6 ${selected.includes(choice.id) ? 'border-primary/40 bg-primary/5' : 'border-border bg-card'}`}><input className="mt-1.5 shrink-0" type={multiple ? 'checkbox' : 'radio'} name={question.id} value={choice.id} checked={selected.includes(choice.id)} onChange={() => setAnswers((current) => ({ ...current, [question.id]: multiple ? (selected.includes(choice.id) ? selected.filter((id) => id !== choice.id) : [...selected, choice.id]) : [choice.id] }))} />{choice.text}</label>; })}
        </fieldset>
      </WorkspacePanel>)}
      <div className="rounded-2xl border border-border bg-card p-4"><Button className="min-h-11 w-full" disabled={busy || questions.some((question) => !(answers[question.id]?.length))}>{busy ? copy.sending : copy.submitAnswers}</Button>{error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}</div>
    </form>}
    <PublicLegalFooter />
  </PublicWorkspace>;
}
