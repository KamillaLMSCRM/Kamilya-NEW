'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { Card, CardHeader, CardTitle, CardContent } from 'ui-kit';

const menuItems = [
  { label: 'Мой дашборд', href: '/student' },
  { label: 'Курсы', href: '/courses' },
  { label: 'AI Генерация', href: '/ai/generate' },
  { label: 'Документы', href: '/documents' },
  { label: 'Сертификаты', href: '/certificates' },
  { label: 'Админ', href: '/admin' },
  { label: 'Настройки', href: '/settings' },
];

export default function DashboardPage() {
  const router = useRouter();
  const { user, initialize } = useAuthStore();

  useEffect(() => {
    initialize();
  }, [initialize]);

  useEffect(() => {
    if (typeof window !== 'undefined' && !useAuthStore.getState().accessToken) {
      router.push('/login');
    }
  }, [router]);

  if (!user) return null;

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-8">
          <span className="text-xl font-bold text-blue-600">Kamilya LMS</span>
          <div className="flex gap-4">
            {menuItems.map((item) => (
              <a key={item.href} href={item.href} className="text-sm text-gray-600 hover:text-blue-600">
                {item.label}
              </a>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-600">
            {user.firstName} {user.lastName}
          </span>
          <a href="/login" className="text-sm text-gray-500 hover:text-red-600" onClick={() => useAuthStore.getState().logout()}>
            Выйти
          </a>
        </div>
      </nav>

      <main className="p-6 max-w-6xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">Панель управления</h1>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>🎓 Мой дашборд</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/student" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>📚 Курсы</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/courses" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>🤖 AI Генерация</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/ai/generate" className="text-blue-600 hover:underline">
                Создать курс →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>📄 Документы</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/documents" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>🏅 Сертификаты</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/certificates" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>🔧 Админ-панель</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/admin" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>⚙️ Настройки</CardTitle>
            </CardHeader>
            <CardContent>
              <a href="/settings" className="text-blue-600 hover:underline">
                Перейти →
              </a>
            </CardContent>
          </Card>
        </div>

        <div className="mt-8">
          <h2 className="text-lg font-semibold mb-4">Привет, {user.firstName}!</h2>
          <p className="text-gray-600">
            Это ваша панель управления Kamilya LMS. Загрузите документы для генерации AI-курсов,
            управляйте сотрудниками и отслеживайте прогресс обучения.
          </p>
        </div>
      </main>
    </div>
  );
}
