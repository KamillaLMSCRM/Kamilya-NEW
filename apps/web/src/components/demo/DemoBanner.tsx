'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { useDemoLimit } from './DemoLimitProvider';
import { Sparkles, X, AlertCircle } from 'lucide-react';
import Link from 'next/link';

interface DemoUsage {
  users?: number;
  courses?: number;
  documents?: number;
  limits?: Record<string, number>;
}

export function DemoBanner() {
  const { t } = useT();
  const user = useAuthStore((s) => s.user);
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const { dismiss } = useDemoLimit();
  const [usage, setUsage] = useState<DemoUsage | null>(null);
  const [dismissed, setDismissed] = useState(false);

  // Only show on demo tenants.
  const isDemo = user?.tenant?.is_demo === true;
  useEffect(() => {
    if (!isDemo) return;
    let cancelled = false;
    (async () => {
      try {
        const token = useAuthStore.getState().accessToken;
        if (!token) return;
        const res = await fetch(`${API_URL}/v1/demo/usage`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok && !cancelled) {
          const data = await res.json();
          setUsage(data);
        }
      } catch {
        // ignore — banner still works without numbers
      }
    })();
    return () => { cancelled = true; };
  }, [isDemo, API_URL]);

  if (!isDemo || dismissed) return null;

  const limits = usage?.limits ?? {};
  return (
    <div className="bg-warning/10 border-b border-warning/30 px-4 py-2 flex items-center justify-between text-sm">
      <div className="flex items-center gap-2 text-warning-foreground">
        <Sparkles className="w-4 h-4" />
        <span className="font-medium">{t('demo.banner.title')}</span>
        <span className="text-text-secondary hidden sm:inline">
          · {t('demo.banner.subtitle')}
        </span>
        {usage && (
          <span className="text-text-secondary text-xs ml-2 hidden md:inline">
            {t('demo.banner.limits', {
              courses: usage.courses ?? 0,
              coursesLimit: limits.courses ?? 5,
              documents: usage.documents ?? 0,
              documentsLimit: limits.documents ?? 2,
              aiToday: 0,
            })}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Link
          href="/register"
          className="text-xs font-medium text-primary hover:underline"
        >
          {t('demo.banner.registerCta')}
        </Link>
        <button
          onClick={() => {
            setDismissed(true);
            dismiss();
          }}
          className="text-text-tertiary hover:text-text-primary p-1"
          aria-label="Dismiss"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}