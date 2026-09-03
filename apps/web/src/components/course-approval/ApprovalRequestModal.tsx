'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Input, Modal } from '@/components/ui';
import { api } from '@/lib/api';
import { createApprovalRequest, freezeApprovalRevision, type ApprovalDeliveryMode, type ApprovalRequestResponse } from '@/lib/courseApproval';
import { toast } from '@/components/ui/Toast';
import { useT } from '@/i18n/useT';

interface Reviewer { id: string; email?: string | null; full_name?: string | null; role?: string | null }
interface GuestReviewer { name: string; email: string }
interface GuestDraft extends GuestReviewer { id: string }
const MAX_GUEST_REVIEWERS = 10;
export interface ApprovalRequestModalProps { open: boolean; courseId: string; onClose: () => void; onCreated?: () => void }

export function ApprovalRequestModal({ open, courseId, onClose, onCreated }: ApprovalRequestModalProps) {
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [deliveryMode, setDeliveryMode] = useState<ApprovalDeliveryMode>('email');
  const [dueAt, setDueAt] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApprovalRequestResponse | null>(null);
  const nextGuestId = useRef(2);
  const [guestRows, setGuestRows] = useState<GuestDraft[]>([{ id: 'guest-1', name: '', email: '' }]);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyFailedKey, setCopyFailedKey] = useState<string | null>(null);
  const { t } = useT();

  useEffect(() => {
    if (!open) return;
    api.get<Reviewer[]>('/v1/users?per_page=500&is_active=true').then((response) => {
      setReviewers(response.data.filter((item) => item.role === 'admin' || item.role === 'methodologist'));
    }).catch(() => setReviewers([]));
  }, [open]);

  async function submit() {
    const guests = guestRows
      .filter((row) => row.name.trim() && row.email.trim().includes('@'))
      .map(({ name, email }) => ({ name: name.trim(), email: email.trim() }));
    if (selected.length === 0 && guests.length === 0) { toast.error(t('courseApproval.selectReviewer')); return; }
    setBusy(true);
    try {
      const revision = await freezeApprovalRevision(courseId);
      const request = await createApprovalRequest(revision.id, selected, deliveryMode, dueAt ? new Date(dueAt).toISOString() : undefined, guests);
      setCreated(request);
      toast.success(t('courseApproval.submit'));
    } catch (error) {
      toast.error(t('courseApproval.errorLoad'), { description: error instanceof Error ? error.message : t('courseApproval.retry') });
    } finally { setBusy(false); }
  }

  function updateGuestRow(id: string, field: keyof GuestReviewer, value: string) {
    setGuestRows((current) => current.map((row) => row.id === id ? { ...row, [field]: value } : row));
  }

  function addGuestRow() {
    setGuestRows((current) => current.length >= MAX_GUEST_REVIEWERS ? current : [...current, { id: `guest-${nextGuestId.current++}`, name: '', email: '' }]);
  }

  function removeGuestRow(id: string) {
    setGuestRows((current) => {
      const next = current.filter((row) => row.id !== id);
      return next.length > 0 ? next : [{ id: `guest-${nextGuestId.current++}`, name: '', email: '' }];
    });
  }

  async function copySecret(value: string, key: string) {
    try {
      if (navigator.clipboard) await navigator.clipboard.writeText(value);
      else throw new Error('clipboard-unavailable');
      setCopiedKey(key); setCopyFailedKey(null);
    } catch {
      const area = document.createElement('textarea');
      area.value = value; area.setAttribute('readonly', 'true'); area.style.position = 'fixed'; area.style.opacity = '0';
      document.body.appendChild(area); area.select();
      try { if (!document.execCommand('copy')) throw new Error('copy-failed'); setCopiedKey(key); setCopyFailedKey(null); }
      catch { setCopyFailedKey(key); toast.error(t('courseApproval.copyFailed')); }
      finally { document.body.removeChild(area); }
    }
  }

  function dismissCredentials() {
    setCreated(null); setCopiedKey(null); setCopyFailedKey(null); onCreated?.(); onClose();
  }

  return <Modal open={open} onClose={dismissCredentials} title={created ? t('courseApproval.credentialsTitle') : t('courseApproval.send')} description={created ? t('courseApproval.credentialsWarning') : t('courseApproval.sendDescription')}>
    <div className="space-y-5">
      {created && <section aria-label={t('courseApproval.credentialsTitle')} className="space-y-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm"><p className="font-semibold">{t('courseApproval.credentialsOneTime')}</p>{(created.access_credentials || []).map((credential) => <div key={credential.reviewer_id} className="space-y-2 rounded border bg-background p-3"><p className="break-all text-xs">{credential.reviewer_id}</p><div className="flex flex-wrap items-center gap-2"><code className="min-w-0 flex-1 break-all text-xs">{credential.access_url}</code><Button type="button" size="sm" variant="outline" onClick={() => void copySecret(credential.access_url, `${credential.reviewer_id}:url`)}>{t('courseApproval.copyUrl')}</Button></div><div className="flex flex-wrap items-center gap-2"><code className="font-mono">{credential.temporary_pin}</code><Button type="button" size="sm" variant="outline" onClick={() => void copySecret(credential.temporary_pin, `${credential.reviewer_id}:pin`)}>{t('courseApproval.copyPin')}</Button></div>{copiedKey?.startsWith(`${credential.reviewer_id}:`) && <span role="status" className="break-words text-xs text-emerald-700">{t('courseApproval.copied')}</span>}{copyFailedKey?.startsWith(`${credential.reviewer_id}:`) && <span role="alert" className="break-words text-xs text-destructive">{t('courseApproval.copyFailed')}</span>}</div>)}{(created.access_credentials || []).length === 0 && <p className="break-words text-muted-foreground">{t('courseApproval.noCredentials')}</p>}<Button type="button" className="w-full" onClick={dismissCredentials}>{t('courseApproval.credentialsAcknowledge')}</Button></section>}
      {!created && <><fieldset className="space-y-2"><legend className="text-sm font-medium">{t('courseApproval.reviewers')}</legend><div className="max-h-48 space-y-2 overflow-y-auto rounded-lg border p-3">{reviewers.length === 0 && <p className="text-sm text-muted-foreground">{t('courseApproval.noReviewers')}</p>}{reviewers.map((reviewer) => { const label = reviewer.full_name || reviewer.email || reviewer.id; return <label key={reviewer.id} className="flex min-h-10 items-center gap-3 text-sm"><input type="checkbox" checked={selected.includes(reviewer.id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, reviewer.id] : current.filter((id) => id !== reviewer.id))} /><span className="min-w-0 break-words">{label}<span className="ml-2 text-xs text-muted-foreground">{reviewer.role === 'admin' ? t('courseApproval.administrator') : t('courseApproval.methodologist')}</span></span></label>; })}</div></fieldset><fieldset className="space-y-2 rounded-lg border p-3"><legend className="text-sm font-medium">{t('courseApproval.externalGuest')}</legend><div className="max-h-72 space-y-3 overflow-y-auto">{guestRows.map((row, index) => <div key={row.id} className="rounded border p-3"><p className="mb-2 text-xs font-medium text-muted-foreground">{t('courseApproval.externalGuest')} {index + 1}</p><div className="grid gap-2 sm:grid-cols-2"><Input aria-label={index === 0 ? t('courseApproval.guestName') : `${t('courseApproval.guestName')} ${index + 1}`} placeholder={t('courseApproval.guestName')} value={row.name} onChange={(event) => updateGuestRow(row.id, 'name', event.target.value)} /><Input aria-label={index === 0 ? t('courseApproval.guestEmail') : `${t('courseApproval.guestEmail')} ${index + 1}`} placeholder={t('courseApproval.guestEmail')} type="email" value={row.email} onChange={(event) => updateGuestRow(row.id, 'email', event.target.value)} /></div><Button type="button" size="sm" variant="outline" aria-label={`${t('courseApproval.removeGuest')} ${index + 1}`} onClick={() => removeGuestRow(row.id)}>{t('courseApproval.removeGuest')}</Button></div>)}</div><Button type="button" size="sm" variant="outline" onClick={addGuestRow} disabled={guestRows.length >= MAX_GUEST_REVIEWERS}>{t('courseApproval.addGuest')}</Button></fieldset><fieldset className="space-y-2"><legend className="text-sm font-medium">{t('courseApproval.delivery')}</legend><div className="grid gap-2 sm:grid-cols-2"><label className="flex min-h-11 items-center gap-2 rounded border p-3 text-sm"><input type="radio" name="delivery" checked={deliveryMode === 'email'} onChange={() => setDeliveryMode('email')} /> {t('courseApproval.email')}</label><label className="flex min-h-11 items-center gap-2 rounded border p-3 text-sm"><input type="radio" name="delivery" checked={deliveryMode === 'personal_link'} onChange={() => setDeliveryMode('personal_link')} /> {t('courseApproval.personalLink')}</label></div></fieldset><label className="block space-y-2 text-sm font-medium">{t('courseApproval.deadline')}<Input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button type="button" variant="outline" onClick={onClose} disabled={busy}>{t('courseApproval.cancel')}</Button><Button type="button" onClick={() => void submit()} disabled={busy}>{busy ? t('courseApproval.sending') : t('courseApproval.submit')}</Button></div></>}
    </div>
  </Modal>;
}
