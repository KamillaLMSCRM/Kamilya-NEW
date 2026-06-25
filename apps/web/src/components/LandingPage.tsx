'use client';

import React from 'react';
import Link from 'next/link';
import { useT } from '@/i18n/useT';
import { Bot, Building2, BarChart3 } from 'lucide-react';

export default function LandingPage() {
  const { t } = useT();
  return (
    <div className="min-h-screen bg-gradient-to-b from-primary/5 to-background">
      <nav className="container mx-auto px-6 py-4 flex justify-between items-center" aria-label={t('nav.dashboard')}>
        <div className="text-2xl font-bold text-primary">Kamilya LMS</div>
        <div className="space-x-4">
          <Link href="/login" className="text-foreground hover:text-primary">
            {t('auth.loginButton')}
          </Link>
          <Link
            href="/register"
            className="bg-primary text-primary-foreground px-4 py-2 rounded-lg hover:bg-primary/90"
          >
            {t('auth.register')}
          </Link>
        </div>
      </nav>

      <main className="container mx-auto px-6 py-20 text-center">
        <h1 className="text-5xl font-bold text-foreground mb-6">
          {t('landing.subtitle')}
        </h1>
        <p className="text-xl text-muted-foreground mb-10 max-w-2xl mx-auto">
          {t('landing.description')}
        </p>
        <div className="flex justify-center gap-4">
          <Link
            href="/register"
            className="bg-primary text-primary-foreground px-8 py-3 rounded-lg text-lg hover:bg-primary/90"
          >
            {t('landing.getStarted')}
          </Link>
          <a
            href="#features"
            className="border border-border text-foreground px-8 py-3 rounded-lg text-lg hover:bg-muted"
          >
            {t('landing.learnMore')}
          </a>
        </div>

        <section id="features" className="mt-24 grid md:grid-cols-3 gap-8">
          <div className="p-6 bg-card rounded-xl shadow-card">
            <div className="mb-4">
              <Bot className="w-12 h-12 text-primary" aria-hidden="true" />
            </div>
            <h3 className="text-xl font-semibold mb-2">{t('landing.features.aiCourses')}</h3>
            <p className="text-muted-foreground">
              {t('landing.features.aiCoursesDesc')}
            </p>
          </div>
          <div className="p-6 bg-card rounded-xl shadow-card">
            <div className="mb-4">
              <Building2 className="w-12 h-12 text-primary" aria-hidden="true" />
            </div>
            <h3 className="text-xl font-semibold mb-2">{t('landing.features.multiTenant')}</h3>
            <p className="text-muted-foreground">
              {t('landing.features.multiTenantDesc')}
            </p>
          </div>
          <div className="p-6 bg-card rounded-xl shadow-card">
            <div className="mb-4">
              <BarChart3 className="w-12 h-12 text-primary" aria-hidden="true" />
            </div>
            <h3 className="text-xl font-semibold mb-2">{t('landing.features.analytics')}</h3>
            <p className="text-muted-foreground">
              {t('landing.features.analyticsDesc')}
            </p>
          </div>
        </section>
      </main>

      <footer className="container mx-auto px-6 py-8 text-center text-muted-foreground border-t mt-20">
        <p>{t('landing.footer')}</p>
      </footer>
    </div>
  );
}
