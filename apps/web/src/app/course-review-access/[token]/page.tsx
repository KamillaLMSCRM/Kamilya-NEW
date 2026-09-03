'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Button, Card, CardContent, Input } from '@/components/ui';
import { getScopedReviewRequest, verifyReviewPin } from '@/lib/courseApproval';

export default function CourseReviewAccessPage() {
  const params = useParams<{ token: string }>();
  const router = useRouter();
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function verify() { setBusy(true); setError(''); try { const result = await verifyReviewPin(params.token, pin); sessionStorage.setItem('course_review_token', result.review_token); let requestId = result.request_id; if (!requestId) { try { requestId = (await getScopedReviewRequest(result.review_token)).request_id; } catch { /* Older API/test doubles may only return the scoped inbox. */ } } router.replace(requestId ? `/course-review-access/review/requests/${requestId}` : '/course-review-access/review'); } catch { sessionStorage.removeItem('course_review_token'); setError('Ссылка недействительна или PIN неверен. Запросите новую ссылку у отправителя.'); } finally { setBusy(false); } }
  return <div className="mx-auto flex min-h-[60vh] max-w-md items-center"><Card className="w-full"><CardContent className="space-y-5 p-6"><div><h1 className="text-xl font-bold">Доступ к проверке курса</h1><p className="mt-1 text-sm text-muted-foreground">Введите шестизначный PIN из письма или кабинета.</p></div><label className="block space-y-2 text-sm font-medium">PIN<Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={pin} onChange={(event) => setPin(event.target.value.replace(/\D/g, ''))} /></label>{error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}<Button className="w-full" disabled={busy || pin.length !== 6} onClick={() => void verify()}>{busy ? 'Проверяем…' : 'Подтвердить доступ'}</Button></CardContent></Card></div>;
}
