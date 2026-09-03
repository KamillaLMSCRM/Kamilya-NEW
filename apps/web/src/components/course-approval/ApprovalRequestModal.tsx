'use client';

import { useEffect, useState } from 'react';
import { Button, Input, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { createApprovalRequest, freezeApprovalRevision, type ApprovalDeliveryMode, type ApprovalRequestResponse } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';

interface Reviewer { id: string; email?: string | null; full_name?: string | null; role?: string | null }
interface GuestReviewer { name: string; email: string }
export interface ApprovalRequestModalProps { open: boolean; courseId: string; onClose: () => void; onCreated?: (request: ApprovalRequestResponse) => void }

export function ApprovalRequestModal({ open, courseId, onClose, onCreated }: ApprovalRequestModalProps) {
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [deliveryMode, setDeliveryMode] = useState<ApprovalDeliveryMode>('email');
  const [dueAt, setDueAt] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApprovalRequestResponse | null>(null);
  const [guest, setGuest] = useState<GuestReviewer>({ name: '', email: '' });
  const [guests, setGuests] = useState<GuestReviewer[]>([]);
  const [copiedReviewer, setCopiedReviewer] = useState<string | null>(null);
  const { t } = useT();

  useEffect(() => {
    if (!open) return;
    api.get<Reviewer[]>('/v1/users?per_page=500&is_active=true').then((response) => {
      setReviewers(response.data.filter((item) => item.role === 'admin' || item.role === 'methodologist'));
    }).catch(() => setReviewers([]));
  }, [open]);

  async function submit() {
    if (selected.length === 0 && guests.length === 0) { toast.error(t('courseApproval.selectReviewer')); return; }
    setBusy(true);
    try {
      const revision = await freezeApprovalRevision(courseId);
      const request = await createApprovalRequest(revision.id, selected, deliveryMode, dueAt ? new Date(dueAt).toISOString() : undefined, guests);
      setCreated(request);
      onCreated?.(request);
      toast.success(t('courseApproval.submit'));
    } catch (error) {
      toast.error(t('courseApproval.errorLoad'), { description: error instanceof Error ? error.message : t('courseApproval.retry') });
    } finally { setBusy(false); }
  }

  async function copyCredential(url: string, pin: string, reviewerId: string) {
    const value = `${url}\nPIN: ${pin}`;
    try {
      if (navigator.clipboard) await navigator.clipboard.writeText(value);
      else throw new Error('clipboard-unavailable');
      setCopiedReviewer(reviewerId);
    } catch {
      const area = document.createElement('textarea'); area.value = value; area.setAttribute('readonly', 'true'); area.style.position = 'fixed'; area.style.opacity = '0'; document.body.appendChild(area); area.select();
      try { document.execCommand('copy'); setCopiedReviewer(reviewerId); } catch { toast.error(t('courseApproval.errorLoad')); } finally { document.body.removeChild(area); }
    }
  }

  return (
    <Modal open={open} onClose={() => { setCreated(null); onClose(); }} title={t('courseApproval.send')} description={t('courseApproval.sendDescription')}>
      <div className="space-y-5">
        {created && <div className="space-y-3 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm"><p className="font-semibold">{t('courseApproval.created')}</p>{created.access_credentials?.map((credential) => <div key={credential.reviewer_id} className="space-y-2 rounded border bg-background p-3"><p className="break-all text-xs">{credential.reviewer_id}</p><p className="break-all font-mono text-xs">{credential.access_url}</p><p className="font-mono">PIN: {credential.temporary_pin}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => void copyCredential(credential.access_url, credential.temporary_pin, credential.reviewer_id)}>{t('courseApproval.copyAccess')}</Button></div></div>)}<Button variant="outline" onClick={() => { setCreated(null); onClose(); }}>{t('courseApproval.close')}</Button></div>}
        {!created && <>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t('courseApproval.reviewers')}</legend>
          <div className="max-h-48 space-y-2 overflow-y-auto rounded-lg border p-3">
            {reviewers.length === 0 && <p className="text-sm text-muted-foreground">{t('courseApproval.noReviewers')}</p>}
            {reviewers.map((reviewer) => {
              const label = reviewer.full_name || reviewer.email || reviewer.id;
              return <label key={reviewer.id} className="flex min-h-10 items-center gap-3 text-sm"><input type="checkbox" checked={selected.includes(reviewer.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, reviewer.id] : current.filter((id) => id !== reviewer.id))} /><span className="min-w-0 break-words">{label}<span className="ml-2 text-xs text-muted-foreground">{reviewer.role === 'admin' ? t('courseApproval.administrator') : t('courseApproval.methodologist')}</span></span></label>;
            })}
          </div>
        </fieldset>
        <fieldset className="space-y-2 rounded-lg border p-3"><legend className="text-sm font-medium">{t('courseApproval.externalGuest')}</legend><div className="grid gap-2 sm:grid-cols-2"><Input aria-label={t('courseApproval.guestName')} placeholder={t('courseApproval.guestName')} value={guest.name} onChange={(event) => setGuest((current) => ({ ...current, name: event.target.value }))} /><Input aria-label={t('courseApproval.guestEmail')} type="email" placeholder={t('courseApproval.guestEmail')} value={guest.email} onChange={(event) => setGuest((current) => ({ ...current, email: event.target.value }))} /></div><Button size="sm" variant="outline" onClick={() => { if (guest.name.trim() && guest.email.includes('@')) { setGuests((current) => [...current, { name: guest.name.trim(), email: guest.email.trim() }]); setGuest({ name: '', email: '' }); } }}>{t('courseApproval.addGuest')}</Button>{guests.length > 0 && <ul className="space-y-1 text-xs">{guests.map((item) => <li key={item.email} className="break-all">{item.name} · {item.email}</li>)}</ul>}</fieldset>
        <fieldset className="space-y-2"><legend className="text-sm font-medium">{t('courseApproval.delivery')}</legend><div className="grid gap-2 sm:grid-cols-2"><label className="flex min-h-11 items-center gap-2 rounded border p-3 text-sm"><input type="radio" name="delivery" checked={deliveryMode === 'email'} onChange={() => setDeliveryMode('email')} /> {t('courseApproval.email')}</label><label className="flex min-h-11 items-center gap-2 rounded border p-3 text-sm"><input type="radio" name="delivery" checked={deliveryMode === 'personal_link'} onChange={() => setDeliveryMode('personal_link')} /> {t('courseApproval.personalLink')}</label></div></fieldset>
        <label className="block space-y-2 text-sm font-medium">{t('courseApproval.deadline')}<Input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="outline" onClick={onClose} disabled={busy}>{t('courseApproval.cancel')}</Button><Button onClick={() => void submit()} disabled={busy}>{busy ? t('courseApproval.sending') : t('courseApproval.submit')}</Button></div></>}
      </div>
    </Modal>
  );
}
