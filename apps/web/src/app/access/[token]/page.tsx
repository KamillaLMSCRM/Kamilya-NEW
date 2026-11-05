'use client';

import { FormEvent, useState } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';

import { Button, Input } from '@/components/ui';
import { PublicWorkspace, WorkspacePanel } from '@/features/workspace-design';
import { getPublicWorkspaceCopy } from '@/features/workspace-design/publicCopy';
import { useAuthStore } from '@/store/authStore';
import type { AuthUser } from '@/lib/auth';
import { runExclusiveAuthAction } from '@/lib/authRefreshCoordinator';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';
import { useT } from '@/i18n/useT';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

function normalizePin(value: string) {
  return value.replace(/\D/g, '').slice(0, 6);
}

export default function AssignmentAccessPage() {
  const params = useParams<{ token: string }>();
  const { t, lang } = useT();
  const copy = getPublicWorkspaceCopy(lang);
  const router = useRouter();
  const login = useAuthStore((state) => state.login);
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || pin.length !== 6 || !params.token) return;
    setBusy(true);
    setError('');
    try {
      await runExclusiveAuthAction(async () => {
        const response = await fetch(`${API_URL}/v1/assignment-access/${encodeURIComponent(params.token)}/exchange`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin }),
        });
        if (!response.ok) throw new Error();
        const data = await response.json() as {
          access_token: string;
          user: AuthUser;
          assigned_course_id: string;
          enrollment_id: string;
        };
        login(data.access_token, data.user);
        router.replace(`/courses/${encodeURIComponent(data.assigned_course_id)}`);
      });
    } catch {
      // This intentionally remains generic: the endpoint does not reveal link state.
      setError(t('publicUi.assignmentAccess.invalid'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicWorkspace id="assignment-access" title={t('publicUi.assignmentAccess.title')} description={t('publicUi.assignmentAccess.subtitle')} icon={<KeyRound />} actions={<LanguageSwitcher />}>
      <div className="mx-auto w-full max-w-lg py-2 sm:py-6">
        <WorkspacePanel title={copy.confirmationStep} bodyClassName="space-y-5">
            <form className="space-y-4" onSubmit={submit}>
              <div>
                <label htmlFor="assignment-pin" className="mb-1.5 block text-sm font-medium">PIN</label>
                <Input id="assignment-pin" value={pin} onChange={(event) => setPin(normalizePin(event.target.value))} inputMode="numeric" autoComplete="one-time-code" placeholder="000000" className="h-12 text-center text-xl tracking-[0.3em]" autoFocus />
              </div>
              <Button type="submit" className="h-11 w-full" disabled={busy || pin.length !== 6}>
                <ShieldCheck className="h-4 w-4" />{busy ? t('publicUi.assignmentAccess.checking') : t('publicUi.assignmentAccess.open')}
              </Button>
              {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
            </form>
        </WorkspacePanel>
      </div>
      <PublicLegalFooter />
    </PublicWorkspace>
  );
}
