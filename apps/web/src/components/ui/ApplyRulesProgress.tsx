'use client';

/**
 * ApplyRulesProgress — поллинг-баннер для apply-rules задачи после
 * импорта штатки. Использует эндпоинт
 * `GET /v1/admin/staff/apply-rules/status/{task_id}` задеплоенный в
 * B1c. Файл появился в этом же эпике; see `staff_import_router.py`.
 *
 * Семантика состояний:
 *   PENDING / RECEIVED / STARTED / RETRY    ── spinner + «обработка»
 *   SUCCESS                                 ── green «✓ готово» + сводка
 *   FAILURE                                 ── red «⚠ ошибка» + сообщение
 *   REVOKED / неизвестное                   ── серый «отменено/неизвестно»
 *
 * Polling — 1.2s. После SUCCESS / FAILURE / REVOKED — stop.
 */

import { useEffect, useRef, useState } from 'react';
import { Card, CardContent, Badge } from '@/components/ui';
import { api } from '@/lib/api';

type TaskState =
  | 'PENDING'
  | 'RECEIVED'
  | 'STARTED'
  | 'SUCCESS'
  | 'FAILURE'
  | 'RETRY'
  | 'REVOKED';

interface StatusResponse {
  task_id: string;
  state: TaskState | string;
  ready: boolean;
  successful?: boolean | null;
  failed?: boolean | null;
  result?: { users_processed?: number; added?: number; removed?: number; failed_user_ids?: string[]; errors?: string[] } | null;
  error?: string | null;
}

interface Props {
  taskId: string;
  /** Колбэк когда задача завершилась (любым терминальным state'ом). */
  onSettled?: () => void;
}

const TERMINAL_STATES = new Set<TaskState>(['SUCCESS', 'FAILURE', 'REVOKED']);

export function ApplyRulesProgress({ taskId, onSettled }: Props) {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [stopped, setStopped] = useState(false);
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      if (cancelled) return;
      try {
        const r = await api.get<StatusResponse>(
          `/v1/admin/staff/apply-rules/status/${taskId}`,
        );
        if (cancelled) return;
        const next = r.data;
        setStatus(next);
        const state = (next?.state ?? 'PENDING') as TaskState;
        if (TERMINAL_STATES.has(state)) {
          setStopped(true);
          onSettledRef.current?.();
          return;
        }
      } catch (err: any) {
        // Polling сами не падаем на сетевых глитчах. Показываем
        // последний известный status, логируем в консоль.
        console.warn('apply-rules poll error', err?.message);
      }
      timer = setTimeout(poll, 1200);
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);

  if (!status) {
    return (
      <Card>
        <CardContent className="p-3 text-xs text-muted-foreground">
          ⏳ Подключаюсь к воркеру…
        </CardContent>
      </Card>
    );
  }

  const state = (status.state ?? 'PENDING') as TaskState;
  const result = status.result ?? null;
  const error = status.error ?? null;

  if (state === 'SUCCESS') {
    return (
      <Card>
        <CardContent className="p-3 text-sm flex items-center gap-3">
          <span className="text-success text-lg">✓</span>
          <div className="flex-1 min-w-0">
            <div className="text-foreground font-medium">
              Применено правил
            </div>
            <div className="text-xs text-muted-foreground">
              {result?.users_processed ?? 0} пользователей · записано{' '}
              {result?.added ?? 0} · убрано {result?.removed ?? 0}
              {result?.failed_user_ids && result.failed_user_ids.length > 0 && (
                <span className="text-warning ml-2">
                  ошибок: {result.failed_user_ids.length}
                </span>
              )}
            </div>
          </div>
          <Badge variant="secondary">{taskId.slice(0, 8)}</Badge>
        </CardContent>
      </Card>
    );
  }

  if (state === 'FAILURE') {
    return (
      <Card>
        <CardContent className="p-3 text-sm flex items-center gap-3">
          <span className="text-destructive text-lg">⚠</span>
          <div className="flex-1 min-w-0">
            <div className="text-foreground font-medium">
              Не удалось применить правила
            </div>
            <div className="text-xs text-destructive truncate">
              {error ?? 'неизвестная ошибка'}
            </div>
          </div>
          <Badge variant="secondary">{taskId.slice(0, 8)}</Badge>
        </CardContent>
      </Card>
    );
  }

  if (state === 'REVOKED') {
    return (
      <Card>
        <CardContent className="p-3 text-sm flex items-center gap-3">
          <span className="text-muted-foreground text-lg">⏸</span>
          <div className="flex-1">
            <div className="text-foreground font-medium">Задача отменена</div>
          </div>
          <Badge variant="secondary">{taskId.slice(0, 8)}</Badge>
        </CardContent>
      </Card>
    );
  }

  // PENDING / STARTED / RETRY — активная работа
  return (
    <Card>
      <CardContent className="p-3 text-sm flex items-center gap-3">
        <span className="inline-block h-3 w-3 rounded-full bg-primary animate-pulse" />
        <div className="flex-1 min-w-0">
          <div className="text-foreground font-medium">
            Применяем правила к сотрудникам…
          </div>
          <div className="text-xs text-muted-foreground">
            state: {state} · опрос каждые 1.2с
            {stopped && ' (polling stopped)'}
          </div>
        </div>
        <Badge variant="secondary">{taskId.slice(0, 8)}</Badge>
      </CardContent>
    </Card>
  );
}
