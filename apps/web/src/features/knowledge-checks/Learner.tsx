'use client';
import { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { OrderingAnswer } from '@/features/quiz/OrderingAnswer';
import { attemptChoiceOrder } from '@/lib/attemptChoiceOrder';
import Link from 'next/link';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { WorkspacePage, WorkspacePanel } from '@/features/workspace-design';
import { base, identity, request, requestError } from './transport';
import { getCopy, statusText } from './copy';
import { Answer, Assignment, Attempt } from './model';

type Page<T> = { items: T[]; has_more: boolean };
type Detail = Assignment & { attempts: Attempt[] };
const button='inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50';
const primary=`${button} bg-primary text-primary-foreground hover:bg-primary/90`;
export default function Learner({ assignmentId }: { assignmentId?: string }) {
  const { user, accessToken, sessionEpoch }=useAuthStore();
  if(!user||!accessToken)return null;
  return <LearnerSession key={JSON.stringify([user.user_id,user.tenant_id,user.role,user.impersonated_by,user.impersonated_role,sessionEpoch,assignmentId])} assignmentId={assignmentId}/>;
}
function LearnerSession({assignmentId}:{assignmentId?:string}) {
  const {lang}=useT(); const c=getCopy(lang); const [scope]=useState(identity); const alive=useCallback(()=>identity()===scope,[scope]);
  const [items,setItems]=useState<Assignment[]>([]);const [offset,setOffset]=useState(0);const [more,setMore]=useState(false); const [detail,setDetail]=useState<Detail|null>(null); const [attempt,setAttempt]=useState<Attempt|null>(null); const [answers,setAnswers]=useState<Answer[]>([]); const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');const [uncertain,setUncertain]=useState(false);const [refresh,setRefresh]=useState(0);
  useEffect(()=>{const controller=new AbortController();setLoading(true);const path=assignmentId?`${base}/assignments/${assignmentId}`:`${base}/my`;request<Detail|Page<Assignment>>(path,{scope,signal:controller.signal,params:assignmentId?undefined:{limit:50,offset}}).then(async value=>{if(!alive()||controller.signal.aborted)return;if(assignmentId){const d=value as Detail;const active=d.attempts.find(a=>a.status==='started');if(active){const a=await request<Attempt>(`${base}/attempts/${active.id}`,{scope,signal:controller.signal});if(!alive()||controller.signal.aborted)return;setAttempt(a);setAnswers(a.answers);}setDetail(d);}else{const p=value as Page<Assignment>;setItems(p.items);setMore(p.has_more);}setUncertain(false);}).catch(()=>{if(alive()&&!controller.signal.aborted)setMessage(c.failed);}).finally(()=>{if(alive()&&!controller.signal.aborted)setLoading(false);});return()=>controller.abort();},[assignmentId,scope,offset,refresh,alive,c.failed]);
  const mutate=async(path:string,method:'POST'|'PUT',data:unknown,done:(a:Attempt)=>void)=>{setBusy(true);setMessage('');try{const a=await request<Attempt>(path,{scope,method,data});if(alive()){done(a);setUncertain(false);}}catch(error){if(alive()){const result=requestError(error,c.failed);setMessage(axios.isAxiosError(error)&&error.response?result.text:c.unknown);setUncertain(result.uncertain);}}finally{if(alive())setBusy(false);}};
  const setOrder = (questionId: string, order: string[]) =>
    setAnswers((current) => [...current.filter((answer) => answer.question_id !== questionId),
      { question_id: questionId, selected_choice_ids: order }]);
  const update=(questionId:string,choiceId:string,multiple:boolean,checked:boolean)=>setAnswers(old=>{const existing=old.find(a=>a.question_id===questionId)?.selected_choice_ids??[];const chosen=multiple?(checked?[...existing,choiceId]:existing.filter(id=>id!==choiceId)):[choiceId];return [...old.filter(a=>a.question_id!==questionId),...(chosen.length?[{question_id:questionId,selected_choice_ids:chosen}]:[])];});
  return <WorkspacePage id="my-knowledge-checks" title={assignmentId?detail?.title??c.my:c.my} actions={assignmentId?<Link href="/my-knowledge-checks" className={button}>{c.back}</Link>:undefined}>
    {message&&<div role={message === c.saved ? 'status' : 'alert'} className={`rounded-xl border p-4 ${message === c.saved ? 'border-primary/30 bg-primary/5' : 'border-destructive'}`}>{message} {message !== c.saved && <button className={button} onClick={()=>{setMessage('');setAttempt(null);setRefresh(v=>v+1);}}>{c.refresh}</button>}</div>}
    {loading?<WorkspacePanel><p role="status">{c.loading}</p></WorkspacePanel>:!assignmentId?<WorkspacePanel>{items.length?<div className="space-y-4">{items.map(item=><article key={item.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3"><div><strong className="break-words">{item.title}</strong><p>{statusText(item.status,c)} · {c.attempts}: {item.attempts_count}/{item.attempt_limit} · {c.score}: {item.score_percent==null?'—':`${item.score_percent}%`}</p><p>{c.deadline}: {item.due_at?new Date(item.due_at).toLocaleString(lang):c.noDeadline}</p></div><Link className={button} href={`/my-knowledge-checks/${item.id}`}>{c.details}</Link></article>)}<div className="flex gap-2"><button className={button} disabled={!offset} onClick={()=>setOffset(Math.max(0,offset-50))}>{c.previous}</button><button className={button} disabled={!more} onClick={()=>setOffset(offset+50)}>{c.next}</button></div></div>:<p>{c.empty}</p>}</WorkspacePanel>:detail&&<>
      <WorkspacePanel bodyClassName="space-y-3"><p>{statusText(detail.status,c)} · {c.attempts}: {detail.attempts_count}/{detail.attempt_limit} · {c.score}: {detail.score_percent==null?'—':`${detail.score_percent}%`}</p><p>{c.deadline}: {detail.due_at?new Date(detail.due_at).toLocaleString(lang):c.noDeadline}</p>{!attempt && !detail.passed && (detail.attempts_count<detail.attempt_limit || detail.status==='in_progress') && <button className={primary} disabled={busy||uncertain} onClick={()=>mutate(`${base}/assignments/${detail.id}/start`,'POST',{},a=>{setAttempt(a);setAnswers(a.answers);})}>{c.start}</button>}</WorkspacePanel>
      {attempt&&!attempt.completed_at&&<WorkspacePanel title={attempt.snapshot.title} description={attempt.snapshot.instructions} bodyClassName="space-y-5"><p>{c.deadline}: {attempt.deadline_at?new Date(attempt.deadline_at).toLocaleString(lang):c.noDeadline}</p>{attempt.snapshot.questions.map((q,i)=><fieldset disabled={busy} key={q.id} className="space-y-3 rounded-xl border border-border p-4"><legend className="px-1 font-medium">{i+1}. {q.text} ({q.points})</legend>{q.type === 'ordering' ? (
        <OrderingAnswer steps={attemptChoiceOrder(q.choices, attempt.assignment_id, q.id, attempt.number - 1)}
          selected={answers.find((answer) => answer.question_id === q.id)?.selected_choice_ids}
          language={lang} disabled={busy} onChange={(order) => setOrder(q.id, order)} />
      ) : attemptChoiceOrder(q.choices, attempt.assignment_id, q.id, attempt.number - 1).map(choice=><label key={choice.id} className="flex min-h-11 items-center gap-3"><input type={q.type==='multiple_choice'?'checkbox':'radio'} name={`answer-${q.id}`} checked={answers.find(a=>a.question_id===q.id)?.selected_choice_ids.includes(choice.id)??false} onChange={e=>update(q.id,choice.id,q.type==='multiple_choice',e.target.checked)}/><span className="break-words">{choice.text}</span></label>)}</fieldset>)}<div className="flex flex-wrap gap-2"><button className={button} disabled={busy||uncertain} onClick={()=>mutate(`${base}/attempts/${attempt.id}/answers`,'PUT',{answers},a=>{setAttempt(a);setAnswers(a.answers);setMessage(c.saved);})}>{c.saveAnswers}</button><button className={primary} disabled={busy||uncertain} onClick={()=>{if(window.confirm(c.confirmSubmit))mutate(`${base}/attempts/${attempt.id}/submit`,'POST',{answers},a=>{setAttempt(a);setAnswers(a.answers);setRefresh(v=>v+1);});}}>{c.submit}</button></div></WorkspacePanel>}
      {attempt?.completed_at&&<WorkspacePanel title={c.results} bodyClassName="space-y-3"><p>{attempt.passed?c.passed:c.notPassed}: {attempt.score_percent==null?'—':`${attempt.score_percent}%`} ({attempt.earned_points}/{attempt.total_points})</p>{!detail.passed&&detail.attempts_count<detail.attempt_limit&&<button className={button} onClick={()=>setAttempt(null)}>{c.start}</button>}</WorkspacePanel>}
      <WorkspacePanel title={c.history}>{detail.attempts.length?<ul className="space-y-2">{detail.attempts.map(a=><li key={a.id}>{c.attempts} {a.number} · {statusText(a.status,c)} · {a.score_percent==null?'—':`${a.score_percent}%`}</li>)}</ul>:<p>{c.empty}</p>}</WorkspacePanel>
    </>}
  </WorkspacePage>;
}
