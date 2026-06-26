'use client';

import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from 'react';
import { Modal, Button } from '@/components/ui';
import { useT } from '@/i18n/useT';
import Link from 'next/link';

interface DemoLimitInfo {
  code: string;
  resource: string;
  limit: number;
  current: number;
  message: string;
  cta?: { text: string; href: string };
}

interface DemoLimitContextValue {
  show: (info: DemoLimitInfo) => void;
  dismiss: () => void;
}

const DemoLimitContext = createContext<DemoLimitContextValue | null>(null);

export function useDemoLimit() {
  const ctx = useContext(DemoLimitContext);
  if (!ctx) throw new Error('useDemoLimit must be used inside DemoLimitProvider');
  return ctx;
}

export function DemoLimitProvider({ children }: { children: ReactNode }) {
  const { t } = useT();
  const [info, setInfo] = useState<DemoLimitInfo | null>(null);

  const show = useCallback((payload: DemoLimitInfo) => setInfo(payload), []);
  const dismiss = useCallback(() => setInfo(null), []);

  // Listen for global 403 events fired by the axios interceptor.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<DemoLimitInfo>).detail;
      setInfo(detail);
    };
    window.addEventListener('demo_limit', handler);
    return () => window.removeEventListener('demo_limit', handler);
  }, []);

  return (
    <DemoLimitContext.Provider value={{ show, dismiss }}>
      {children}
      <Modal
        open={info !== null}
        onClose={dismiss}
        title={info?.message || t('demo.limitModal.defaultMessage')}
      >
        {info && (
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              {info.message}
            </p>
            {info.cta && (
              <Link href={info.cta.href}>
                <Button variant="default" className="w-full">
                  {info.cta.text}
                </Button>
              </Link>
            )}
            <Button
              variant="secondary"
              className="w-full"
              onClick={dismiss}
            >
              {t('demo.limitModal.closeCta')}
            </Button>
          </div>
        )}
      </Modal>
    </DemoLimitContext.Provider>
  );
}