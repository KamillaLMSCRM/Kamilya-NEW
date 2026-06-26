'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { clearStoredAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Logo } from '@/components/brand/Logo';
import { Shield, BookOpen, GraduationCap, ArrowLeft, KeyRound } from 'lucide-react';

interface RoleCard {
  role: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
  redirect: string;
}

const ROLES: RoleCard[] = [
  {
    role: 'admin',
    title: 'Администратор',
    description: 'Управление курсами, пользователями и настройками платформы',
    icon: <Shield className="w-8 h-8" />,
    color: 'text-primary',
    bg: 'bg-primary/10 hover:bg-primary/15 border-primary/20',
    redirect: '/dashboard',
  },
  {
    role: 'teacher',
    title: 'Методолог',
    description: 'Создание и редактирование курсов, просмотр прогресса студентов',
    icon: <BookOpen className="w-8 h-8" />,
    color: 'text-success',
    bg: 'bg-success/10 hover:bg-success/15 border-success/30',
    redirect: '/courses',
  },
  {
    role: 'student',
    title: 'Обучающийся',
    description: 'Прохождение курсов, тестов и получение сертификатов',
    icon: <GraduationCap className="w-8 h-8" />,
    color: 'text-accent',
    bg: 'bg-accent/10 hover:bg-accent/15 border-accent/30',
    redirect: '/my-courses',
  },
];

export default function DemoLoginPage() {
  const router = useRouter();
  const { login } = useAuthStore();
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState('');

  const handleDemoLogin = async (card: RoleCard) => {
    setLoading(card.role);
    setError('');
    try {
      clearStoredAuth();
      const res = await api.post('/v1/auth/demo-login', { role: card.role });
      login(res.data.access_token, res.data.user);
      router.push(card.redirect);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Ошибка входа');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-primary/5 to-background">
      <main className="w-full max-w-2xl p-8">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <Logo variant="full" size={44} />
          </div>
          <h2 className="text-xl font-semibold mt-2 text-foreground">Демо-доступ</h2>
          <p className="text-sm text-muted-foreground mt-2">
            Выберите роль для входа в систему
          </p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-destructive/10 text-destructive rounded-lg text-sm" role="alert">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 gap-4">
          {ROLES.map((card) => (
            <button
              key={card.role}
              onClick={() => handleDemoLogin(card)}
              disabled={loading !== null}
              className={`flex items-center gap-5 p-6 rounded-xl border-2 text-left transition-all duration-200 ${card.bg} ${loading === card.role ? 'opacity-60 cursor-wait' : 'cursor-pointer'}`}
            >
              <div className={`shrink-0 ${card.color}`}>
                {loading === card.role ? (
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-current" />
                ) : (
                  card.icon
                )}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-foreground text-lg">{card.title}</div>
                <div className="text-sm text-muted-foreground mt-0.5">{card.description}</div>
              </div>
              <svg className="w-5 h-5 text-muted-foreground/60 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>

        <div className="mt-8 pt-6 border-t border-border text-center space-y-3">
          <a
            href="/superadmin/login"
            className="inline-flex items-center gap-1.5 text-sm text-warning hover:text-warning/80 transition-colors"
          >
            <KeyRound className="w-4 h-4" />
            Вход для оператора платформы (суперадмин)
          </a>
          <div>
            <a
              href="/login"
              className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-primary transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Назад к входу через Telegram
            </a>
          </div>
        </div>
      </main>
    </div>
  );
}
