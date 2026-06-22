'use client';

import React from 'react';
import { useT } from '@/i18n/useT';
import { Bot, Building2, BarChart3 } from 'lucide-react';

interface LandingPageProps {}

export default function LandingPage({}: LandingPageProps) {
  const { t } = useT();
  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white">
      <nav className="container mx-auto px-6 py-4 flex justify-between items-center">
        <div className="text-2xl font-bold text-blue-600">Kamilya LMS</div>
        <div className="space-x-4">
          <a href="/login" className="text-gray-700 hover:text-blue-600">
            {t('auth.loginButton')}
          </a>
          <a
            href="/register"
            className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
          >
            {t('auth.register')}
          </a>
        </div>
      </nav>

      <main className="container mx-auto px-6 py-20 text-center">
        <h1 className="text-5xl font-bold text-gray-900 mb-6">
          {t('landing.subtitle')}
        </h1>
        <p className="text-xl text-gray-600 mb-10 max-w-2xl mx-auto">
          {t('landing.description')}
        </p>
        <div className="flex justify-center gap-4">
          <a
            href="/register"
            className="bg-blue-600 text-white px-8 py-3 rounded-lg text-lg hover:bg-blue-700"
          >
            {t('landing.getStarted')}
          </a>
          <a
            href="#features"
            className="border border-gray-300 text-gray-700 px-8 py-3 rounded-lg text-lg hover:bg-gray-50"
          >
            {t('landing.learnMore')}
          </a>
        </div>

        <section id="features" className="mt-24 grid md:grid-cols-3 gap-8">
          <div className="p-6 bg-white rounded-xl shadow-sm">
            <div className="mb-4"><Bot className="w-12 h-12 text-blue-600" /></div>
            <h3 className="text-xl font-semibold mb-2">{t('landing.features.aiCourses')}</h3>
            <p className="text-gray-600">
              Загрузите документы — AI создаст структуру, контент и тесты за минуты.
            </p>
          </div>
          <div className="p-6 bg-white rounded-xl shadow-sm">
            <div className="mb-4"><Building2 className="w-12 h-12 text-blue-600" /></div>
            <h3 className="text-xl font-semibold mb-2">Multi-tenant SaaS</h3>
            <p className="text-gray-600">
              Полная изоляция данных между компаниями. Каждый тенант — отдельный мир.
            </p>
          </div>
          <div className="p-6 bg-white rounded-xl shadow-sm">
            <div className="mb-4"><BarChart3 className="w-12 h-12 text-blue-600" /></div>
            <h3 className="text-xl font-semibold mb-2">Аналитика в реальном времени</h3>
            <p className="text-gray-600">
              Отслеживайте прогресс сотрудников с помощью дашбордов и отчётов.
            </p>
          </div>
        </section>
      </main>

      <footer className="container mx-auto px-6 py-8 text-center text-gray-500 border-t mt-20">
        <p>© 2026 Kamilya LMS. AI-first корпоративное обучение для Казахстана.</p>
      </footer>
    </div>
  );
}
