'use client';

import { FormEvent, useState } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';

import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui';
import { Logo } from '@/components/brand/Logo';
import { getRoleHome } from '@/lib/rolePolicy';
import { useAuthStore } from '@/store/authStore';
import type { AuthUser } from '@/lib/auth';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

function normalizePin(value: string) {
  return value.replace(/\D/g, '').slice(0, 6);
}

export default function AssignmentAccessPage() {
  const params = useParams<{ token: string }>();
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
      const response = await fetch(`${API_URL}/v1/assignment-access/${encodeURIComponent(params.token)}/exchange`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      });
      if (!response.ok) throw new Error();
      const data = await response.json() as { access_token: string; user: AuthUser };
      login(data.access_token, data.user);
      router.replace(getRoleHome(data.user.role));
    } catch {
      // This intentionally remains generic: the endpoint does not reveal link state.
      setError('Ссылка или PIN недействительны. Проверьте данные или запросите новую ссылку у методолога.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <main className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Logo variant="full" size={40} /></div>
        <Card>
          <CardHeader>
            <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-md bg-primary/10 text-primary"><KeyRound className="h-6 w-6" /></div>
            <CardTitle>Доступ к назначенному обучению</CardTitle>
            <p className="text-sm text-muted-foreground">Введите шестизначный PIN, выданный вместе со ссылкой.</p>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={submit}>
              <div>
                <label htmlFor="assignment-pin" className="mb-1.5 block text-sm font-medium">PIN</label>
                <Input id="assignment-pin" value={pin} onChange={(event) => setPin(normalizePin(event.target.value))} inputMode="numeric" autoComplete="one-time-code" placeholder="000000" className="h-12 text-center text-xl tracking-[0.3em]" autoFocus />
              </div>
              <Button type="submit" className="h-11 w-full" disabled={busy || pin.length !== 6}>
                <ShieldCheck className="h-4 w-4" />{busy ? 'Проверяем...' : 'Открыть обучение'}
              </Button>
              {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}
            </form>
          </CardContent>
        </Card>
      </main>
      <PublicLegalFooter />
    </div>
  );
}
