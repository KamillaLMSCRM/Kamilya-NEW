'use client';

import React from 'react';
import Link from 'next/link';
import { AlertTriangle, ArrowLeft, RefreshCw } from 'lucide-react';
import { useT } from '@/i18n/useT';

interface ErrorPageProps {
  statusCode: number;
  title: string;
  message: string;
}

export function ErrorPage({ statusCode, title, message }: ErrorPageProps) {
  const { t } = useT();
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="text-center max-w-md">
        <AlertTriangle className="w-16 h-16 text-destructive mx-auto mb-6" aria-hidden="true" />
        <div className="text-6xl font-bold text-destructive mb-4">{statusCode}</div>
        <h1 className="text-2xl font-bold text-foreground mb-2">{title}</h1>
        <p className="text-muted-foreground mb-8">{message}</p>
        <div className="flex gap-3 justify-center">
          <Link
            href="/"
            className="flex items-center gap-2 px-4 py-2 border border-border rounded-lg hover:bg-muted transition-colors"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
            {t('errorPage.goHome')}
          </Link>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors"
          >
            <RefreshCw className="w-4 h-4" aria-hidden="true" />
            {t('errorPage.refresh')}
          </button>
        </div>
      </div>
    </div>
  );
}

export function NotFoundPage() {
  const { t } = useT();
  return (
    <ErrorPage
      statusCode={404}
      title={t('errorPage.notFoundTitle')}
      message={t('errorPage.notFoundMessage')}
    />
  );
}

export function ServerErrorPage() {
  const { t } = useT();
  return (
    <ErrorPage
      statusCode={500}
      title={t('errorPage.serverErrorTitle')}
      message={t('errorPage.serverErrorMessage')}
    />
  );
}
