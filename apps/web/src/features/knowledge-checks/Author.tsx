'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { OrderingButtons, moveOrderingStep, orderingCopy } from '@/features/quiz/OrderingAnswer';
import { useT } from '@/i18n/useT';
import { useAuthStore } from '@/store/authStore';
import { WorkspacePage, WorkspacePanel } from '@/features/workspace-design';
import { base, identity, request, requestError } from './transport';
import { getCopy, statusText } from './copy';
import { Check, Content, Question, newContent, newQuestion, uuid } from './model';
type Page<T> = {
    items: T[];
    has_more: boolean;
};
type Employee = {
    id: string;
    first_name: string;
    last_name: string;
    email: string | null;
    personnel_number: string | null;
    role: string;
    is_active: boolean;
    status: string;
};
type Roster = {
    users: Employee[];
    total: number;
    page: number;
    per_page: number;
};
const employeeLabel = (employee: Employee) => [employee.last_name, employee.first_name].filter(Boolean).join(' ').trim()
    || employee.email || employee.personnel_number || employee.id;
type Result = {
    id: string;
    employee_label: string;
    status: string;
    revision: number;
    due_at: string | null;
    attempts: {
        id: string;
        number: number;
        status: string;
        score_percent: number | null;
        passed: boolean | null;
    }[];
};
const input = 'w-full min-w-0 rounded-lg border border-border bg-background px-3 py-2 text-foreground';
const button = 'inline-flex min-h-11 items-center justify-center rounded-xl border border-border px-4 py-2 text-sm font-medium hover:bg-muted disabled:opacity-50';
const primary = `${button} bg-primary text-primary-foreground hover:bg-primary/90`;
export default function Author() {
    const { user, accessToken, sessionEpoch } = useAuthStore();
    if (!user || !accessToken)
        return null;
    return <AuthorSession key={JSON.stringify([user.user_id, user.tenant_id, user.role, user.impersonated_by, user.impersonated_role, sessionEpoch])}/>;
}
function AuthorSession() {
    const { lang } = useT();
    const c = getCopy(lang);
    const [scope] = useState(identity);
    const [list, setList] = useState<Check[]>([]);
    const [offset, setOffset] = useState(0);
    const [more, setMore] = useState(false);
    const [record, setRecord] = useState<Check | null>(null);
    const [content, setContent] = useState<Content | null>(null);
    const [createId, setCreateId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const [uncertain, setUncertain] = useState(false);
    const [employees, setEmployees] = useState<Employee[]>([]);
    const [employeePage, setEmployeePage] = useState(1);
    const [employeeTotal, setEmployeeTotal] = useState(0);
    const [search, setSearch] = useState('');
    const [query, setQuery] = useState('');
    const [selected, setSelected] = useState<Record<string, string>>({});
    const [due, setDue] = useState('');
    const [results, setResults] = useState<Result[] | null>(null);
    const [resultOffset, setResultOffset] = useState(0);
    const [resultMore, setResultMore] = useState(false);
    const alive = useCallback(() => identity() === scope, [scope]);
    const dirty = content !== null && (record === null || JSON.stringify(content) !== JSON.stringify(record));
    const discardText = lang === 'kk' ? 'Сақталмаған өзгерістерді жою керек пе?'
        : lang === 'en' ? 'Discard unsaved changes?' : 'Отменить несохранённые изменения?';
    const removeChoicesText = lang === 'kk' ? 'Екі нұсқадан кейінгі жауаптар жойылады. Жалғастыру керек пе?'
        : lang === 'en' ? 'Choices after the first two will be removed. Continue?'
            : 'Варианты после первых двух будут удалены. Продолжить?';
    useEffect(() => {
        if (!dirty)
            return;
        const beforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            event.returnValue = '';
        };
        window.addEventListener('beforeunload', beforeUnload);
        return () => window.removeEventListener('beforeunload', beforeUnload);
    }, [dirty]);
    const canDiscard = () => !dirty || window.confirm(discardText);
    const audienceGeneration = useRef(0);
    const resetAudience = () => {
        audienceGeneration.current += 1;
        setEmployees([]);
        setEmployeeTotal(0);
        setEmployeePage(1);
        setSearch('');
        setQuery('');
        setSelected({});
        setDue('');
    };
    useEffect(() => { const controller = new AbortController(); setLoading(true); request<Page<Check>>(base + '/', { scope, params: { limit: 50, offset }, signal: controller.signal }).then(x => { if (alive()) {
        setList(x.items);
        setMore(x.has_more);
    } }).catch(() => { if (alive() && !controller.signal.aborted)
        setMessage(c.failed); }).finally(() => { if (alive() && !controller.signal.aborted)
        setLoading(false); }); return () => controller.abort(); }, [scope, offset, alive, c.failed]);
    useEffect(() => {
        if (!record || record.status !== 'published')
            return;
        const controller = new AbortController();
        const generation = ++audienceGeneration.current;
        setEmployees([]);
        setEmployeeTotal(0);
        request<Roster>('/v1/users', {
            scope,
            params: { role: 'student', is_active: true, page: employeePage, per_page: 20, search: query || undefined },
            signal: controller.signal,
        }).then((response) => {
            if (!alive() || controller.signal.aborted || generation !== audienceGeneration.current)
                return;
            if (!Array.isArray(response.users) || !Number.isSafeInteger(response.total) || response.total < 0
                || response.page !== employeePage || response.per_page !== 20
                || response.users.some((employee) => !employee.id || typeof employee.role !== 'string'
                    || typeof employee.is_active !== 'boolean' || typeof employee.status !== 'string')) {
                throw new Error('Invalid audience response');
            }
            setEmployees(response.users.filter((employee) => employee.role === 'student'
                && employee.is_active === true && employee.status === 'active'));
            setEmployeeTotal(response.total);
        }).catch(() => {
            if (alive() && !controller.signal.aborted && generation === audienceGeneration.current) {
                setEmployees([]);
                setEmployeeTotal(0);
                setMessage(c.failed);
            }
        });
        return () => controller.abort();
    }, [record, scope, employeePage, query, alive, c.failed]);
    const open = async (id: string) => {
        if (!canDiscard())
            return;
        resetAudience();
        setBusy(true);
        setMessage('');
        try {
            const next = await request<Check>(`${base}/${id}`, { scope });
            if (alive()) {
                setRecord(next);
                setContent(next);
                setCreateId(null);
                setResults(null);
                setUncertain(false);
            }
        }
        catch (error) {
            if (alive()) {
                if (!record && createId === id && axios.isAxiosError(error) && error.response?.status === 404)
                    setUncertain(false);
                setMessage(c.failed);
            }
        }
        finally {
            if (alive())
                setBusy(false);
        }
    };
    const mutate = async (path: string, method: 'POST' | 'PUT', data: unknown, success: (v: any) => void) => { setBusy(true); setMessage(''); try {
        const x = await request<any>(path, { scope, method, data });
        if (alive()) {
            success(x);
            setUncertain(false);
        }
    }
    catch (error) {
        if (alive()) {
            const result = requestError(error, c.failed);
            setMessage(axios.isAxiosError(error) && error.response ? result.text : c.unknown);
            setUncertain(result.uncertain);
        }
    }
    finally {
        if (alive())
            setBusy(false);
    } };
    const updateQuestion = (index: number, change: Partial<Question>) => setContent(x => x && ({ ...x, questions: x.questions.map((q, i) => i === index ? { ...q, ...change } : q) }));
    const loadResults = async (skip = 0) => { if (!record)
        return; setBusy(true); try {
        const x = await request<Page<Result>>(`${base}/${record.id}/results`, { scope, params: { limit: 50, offset: skip } });
        if (alive()) {
            setResults(x.items);
            setResultOffset(skip);
            setResultMore(x.has_more);
            setMessage('');
        }
    }
    catch {
        if (alive())
            setMessage(c.failed);
    }
    finally {
        if (alive())
            setBusy(false);
    } };
    const orderCopy = orderingCopy(lang);
    const valid = (x: Content) => x.title.trim() && x.questions.length && x.questions.every(q => q.text.trim() && q.points > 0 && q.choices.length >= 2 && q.choices.every(o => o.text.trim()) && (q.type === 'ordering' ? new Set(q.choices.map(o => o.text.trim().toLowerCase())).size === q.choices.length : q.type === 'multiple_choice' ? q.choices.some(o => o.is_correct) && q.choices.some(o => !o.is_correct) : q.choices.filter(o => o.is_correct).length === 1) && (q.type !== 'true_false' || q.choices.length === 2));
    return <WorkspacePage id="knowledge-checks" title={c.title}>
    {message && <div role={[c.created,c.assigned,c.published].includes(message) ? 'status' : 'alert'} className={`rounded-xl border p-4 ${[c.created,c.assigned,c.published].includes(message) ? 'border-primary/30 bg-primary/5' : 'border-destructive'}`}>{message}</div>}
    <WorkspacePanel actions={<button className={primary} type="button" disabled={busy || uncertain} onClick={() => { if (!canDiscard())
        return; resetAudience(); setRecord(null); setCreateId(uuid()); setContent(newContent()); setResults(null); setSelected({}); setMessage(''); setUncertain(false); }}>{c.create}</button>}>
      {loading ? <p role="status">{c.loading}</p> : list.length ? <div className="space-y-3">{list.map(x => <div key={x.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3"><div><strong className="break-words">{x.title}</strong><p>{statusText(x.status, c)} · {c.revision} {x.revision}</p></div><button type="button" className={button} disabled={busy} onClick={() => open(x.id)}>{c.details}</button></div>)}<div className="flex gap-2"><button className={button} disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>{c.previous}</button><button className={button} disabled={!more} onClick={() => setOffset(offset + 50)}>{c.next}</button></div></div> : <p>{c.empty}</p>}
    </WorkspacePanel>
    {content && <WorkspacePanel title={record ? `${c.edit}: ${record.title}` : c.create} bodyClassName="space-y-4"><fieldset disabled={busy} className="min-w-0 space-y-4">
      <label className="block space-y-1">{c.name}<input className={input} value={content.title} onChange={e => setContent({ ...content, title: e.target.value })}/></label>
      <label className="block space-y-1">{c.instructions}<textarea className={input} value={content.instructions} onChange={e => setContent({ ...content, instructions: e.target.value })}/></label>
      <div className="grid gap-3 sm:grid-cols-3"><label>{c.pass}<input className={input} type="number" min="0" max="100" value={content.pass_score} onChange={e => setContent({ ...content, pass_score: Number(e.target.value) })}/></label><label>{c.limit}<input className={input} type="number" min="1" value={content.attempt_limit} onChange={e => setContent({ ...content, attempt_limit: Number(e.target.value) })}/></label><label>{c.time}<input className={input} type="number" min="1" value={content.time_limit_minutes ?? ''} onChange={e => setContent({ ...content, time_limit_minutes: e.target.value ? Number(e.target.value) : null })}/></label></div>
      <h3 className="font-semibold">{c.questions}</h3>{content.questions.map((q, i) => <fieldset key={q.id} className="space-y-3 rounded-xl border border-border p-4"><legend className="px-1 font-medium">{c.question} {i + 1}</legend><label className="block">{c.question}<textarea className={input} value={q.text} onChange={e => updateQuestion(i, { text: e.target.value })}/></label><div className="grid gap-3 sm:grid-cols-2"><label>{c.kind}<select className={input} value={q.type} onChange={e => { const type = e.target.value as Question['type']; if (type === 'true_false' && q.choices.length > 2 && !window.confirm(removeChoicesText))
            return; const choices = type === 'true_false' ? q.choices.slice(0, 2) : q.choices; updateQuestion(i, { type, choices }); }}><option value="MCQ">{c.single}</option><option value="multiple_choice">{c.multiple}</option><option value="true_false">{c.boolean}</option><option value="ordering">{orderCopy.type}</option></select></label><label>{c.points}<input className={input} type="number" min="1" value={q.points} onChange={e => updateQuestion(i, { points: Number(e.target.value) })}/></label></div><label className="block">{c.explanation}<textarea className={input} value={q.explanation} onChange={e => updateQuestion(i, { explanation: e.target.value })}/></label>{q.type === 'ordering' && <p className="text-sm text-muted-foreground">{orderCopy.format}</p>}
      {q.choices.map((o, j) => <div key={o.id} className="flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1">{q.type === 'ordering' ? orderCopy.step : c.choice} {j + 1}<input className={input} value={o.text} onChange={e => updateQuestion(i, { choices: q.choices.map((v, k) => k === j ? { ...v, text: e.target.value } : v) })}/></label>{q.type === 'ordering' ? <OrderingButtons index={j} count={q.choices.length} label={o.text || `${orderCopy.step} ${j + 1}`}
        lang={lang} onMove={(offset) => updateQuestion(i, { choices: moveOrderingStep(q.choices, j, offset) })} />
        : <label className="flex min-h-11 items-center gap-2"><input type={q.type === 'multiple_choice' ? 'checkbox' : 'radio'} name={`key-${q.id}`} checked={o.is_correct} onChange={e => updateQuestion(i, { choices: q.choices.map((v, k) => ({ ...v, is_correct: q.type === 'multiple_choice' ? (k === j ? e.target.checked : v.is_correct) : k === j })) })}/>{c.correct}</label>}{q.choices.length > 2 && <button className={button} type="button" onClick={() => updateQuestion(i, { choices: q.choices.filter((_, k) => k !== j) })}>{c.remove}</button>}</div>)}<div className="flex flex-wrap gap-2">{q.type !== 'true_false' && <button className={button} type="button" onClick={() => updateQuestion(i, { choices: [...q.choices, { id: uuid(), text: '', is_correct: false }] })}>{c.addChoice}</button>}{content.questions.length > 1 && <button className={button} type="button" onClick={() => setContent({ ...content, questions: content.questions.filter((_, j) => j !== i) })}>{c.remove}</button>}</div></fieldset>)}
      <div className="flex flex-wrap gap-2"><button className={button} type="button" onClick={() => setContent({ ...content, questions: [...content.questions, newQuestion()] })}>{c.addQuestion}</button><button className={primary} type="button" disabled={busy || uncertain} onClick={() => { if (!valid(content)) {
            setMessage(c.invalid);
            return;
        } const { title, instructions, pass_score, attempt_limit, time_limit_minutes, questions } = content; const body = { title, instructions, pass_score, attempt_limit, time_limit_minutes, questions }; mutate(record ? `${base}/${record.id}` : base + '/', record ? 'PUT' : 'POST', record ? { ...body, expected_revision: record.revision } : { ...body, id: createId }, x => { resetAudience(); setRecord(x); setContent(x); setCreateId(null); setMessage(c.created); setOffset(0); setList(old => [x, ...old.filter(y => y.id !== x.id)]); }); }}>{c.save}</button>{(record || createId) && <button className={button} disabled={busy} type="button" onClick={() => open(record?.id ?? createId!)}>{c.refresh}</button>}{record && record.status === 'draft' && <button className={button} disabled={busy || uncertain || JSON.stringify(content) !== JSON.stringify(record)} type="button" onClick={() => mutate(`${base}/${record.id}/publish`, 'POST', { expected_revision: record.revision }, x => { resetAudience(); setRecord(x); setContent(x); setList(old => old.map(y => y.id === x.id ? x : y)); setMessage(c.published); })}>{c.publish}</button>}</div>
    </fieldset></WorkspacePanel>}
    {record && <WorkspacePanel title={c.results} actions={<button className={button} disabled={busy} onClick={() => loadResults()}>{c.results}</button>}>{results && (results.length ? <div className="space-y-4">{results.map(x => <div key={x.id}><strong>{x.employee_label}</strong> · {statusText(x.status, c)} · {c.revision} {x.revision}<ul>{x.attempts.map(a => <li key={a.id}>{c.attempts} {a.number}: {statusText(a.status, c)} · {a.score_percent == null ? '—' : `${a.score_percent}%`}</li>)}</ul></div>)}<div className="flex gap-2"><button className={button} disabled={!resultOffset} onClick={() => loadResults(Math.max(0, resultOffset - 50))}>{c.previous}</button><button className={button} disabled={!resultMore} onClick={() => loadResults(resultOffset + 50)}>{c.next}</button></div></div> : <p>{c.empty}</p>)}</WorkspacePanel>}
    {record?.status === 'published' && <WorkspacePanel title={c.assign} bodyClassName="space-y-4"><fieldset disabled={busy} className="space-y-4"><form className="flex flex-wrap gap-2" onSubmit={e => { e.preventDefault(); setEmployeePage(1); setQuery(search.trim()); }}><label className="min-w-0 flex-1">{c.search}<input className={input} value={search} onChange={e => setSearch(e.target.value)}/></label><button className={button}>{c.search}</button></form><p>{c.employees} · {c.selected}: {Object.keys(selected).length}</p><ul className="space-y-2">{employees.map(e => <li key={e.id}><label className="flex items-center gap-2"><input type="checkbox" checked={!!selected[e.id]} onChange={v => setSelected(old => { const next = { ...old }; if (v.target.checked)
        next[e.id] = employeeLabel(e);
    else
        delete next[e.id]; return next; })}/><span>{employeeLabel(e)}{e.personnel_number ? ` · ${e.personnel_number}` : ''}</span></label></li>)}</ul><div className="flex gap-2"><button className={button} disabled={employeePage <= 1} onClick={() => setEmployeePage(employeePage - 1)}>{c.previous}</button><button className={button} disabled={employeePage * 20 >= employeeTotal} onClick={() => setEmployeePage(employeePage + 1)}>{c.next}</button></div>{Object.keys(selected).length > 0 && <div><p>{c.selected}:</p><ul>{Object.entries(selected).map(([id, name]) => <li key={id} className="flex items-center gap-2">{name}<button className={button} onClick={() => setSelected(old => { const next = { ...old }; delete next[id]; return next; })}>{c.remove}</button></li>)}</ul><button className={button} onClick={() => setSelected({})}>{c.clear}</button></div>}<label className="block">{c.due}<input className={input} type="datetime-local" value={due} onChange={e => setDue(e.target.value)}/></label><button className={primary} disabled={busy || uncertain || JSON.stringify(content) !== JSON.stringify(record) || !Object.keys(selected).length} onClick={() => mutate(`${base}/${record.id}/assign`, 'POST', { expected_revision: record.revision, user_ids: Object.keys(selected), due_at: due ? new Date(due).toISOString() : null }, () => { setSelected({}); setMessage(c.assigned); })}>{c.assign}</button></fieldset></WorkspacePanel>}
  </WorkspacePage>;
}
