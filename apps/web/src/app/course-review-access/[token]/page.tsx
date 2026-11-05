'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Button, Input } from '@/components/ui';
import { getScopedReviewRequest, verifyReviewPin } from '@/lib/courseApproval';
import { PublicWorkspace, WorkspacePanel } from '@/features/workspace-design';
import { getPublicWorkspaceCopy } from '@/features/workspace-design/publicCopy';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';
import { useT } from '@/i18n/useT';

export default function CourseReviewAccessPage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const { lang } = useT();
  const copy = getPublicWorkspaceCopy(lang);
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function verify() { setBusy(true); setError(''); try { const result = await verifyReviewPin(params.token, pin); sessionStorage.setItem('course_review_token', result.review_token); let requestId = result.request_id; if (!requestId) { try { requestId = (await getScopedReviewRequest(result.review_token)).request_id; } catch { /* Older API/test doubles may only return the scoped inbox. */ } } router.replace(requestId ? `/course-review-access/review/requests/${requestId}` : '/course-review-access/review'); } catch { sessionStorage.removeItem('course_review_token'); setError(copy.reviewInvalid); } finally { setBusy(false); } }
  return <PublicWorkspace id="review-access" title={copy.reviewAccessTitle} description={copy.reviewAccessHint} actions={<LanguageSwitcher />}>
    <div className="mx-auto w-full max-w-lg py-2 sm:py-6">
      <WorkspacePanel title={copy.confirmationStep} bodyClassName="space-y-5">
        <label className="block space-y-2 text-sm font-medium">PIN<Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={pin} onChange={(event) => setPin(event.target.value.replace(/\D/g, ''))} className="h-12 text-center text-xl tracking-[0.3em]" /></label>
        {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm leading-6 text-destructive">{error}</p>}
        <Button type="button" className="min-h-11 w-full" disabled={busy || pin.length !== 6} onClick={() => void verify()}>{busy ? copy.checking : copy.confirmAccess}</Button>
      </WorkspacePanel>
    </div>
    <PublicLegalFooter />
  </PublicWorkspace>;
}
