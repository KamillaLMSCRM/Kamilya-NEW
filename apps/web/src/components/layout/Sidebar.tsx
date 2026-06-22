'use client';

import { useAuthStore } from '@/store/authStore';
import { usePathname } from 'next/navigation';
import { useT } from '@/i18n/useT';

interface NavItem {
  label: string;
  href: string;
  icon: string;
  roles?: string[];
}

export default function Sidebar() {
  const { t } = useT();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const navSections: { title: string; items: NavItem[] }[] = [
    {
      title: t('nav.aiGeneration'),
      items: [
        { label: t('nav.documents'), href: '/documents', icon: '📄' },
        { label: 'Должности', href: '/positions', icon: '💼' },
        { label: 'Job Descriptions', href: '/job-descriptions', icon: '📋' },
        { label: t('nav.aiGeneration'), href: '/ai/generate', icon: '🤖' },
      ],
    },
    {
      title: t('nav.courses'),
      items: [
        { label: t('nav.courses'), href: '/courses', icon: '📚' },
        { label: t('student.enrolledCourses'), href: '/my-courses', icon: '🎓' },
        { label: t('nav.certificates'), href: '/certificates', icon: '🏅' },
      ],
    },
    {
      title: t('settings.title'),
      items: [
        { label: t('nav.userManagement'), href: '/admin/users', icon: '👥', roles: ['admin', 'superadmin'] },
        { label: t('courses.enrollments'), href: '/admin/enrollments', icon: '📋', roles: ['admin', 'superadmin'] },
        { label: t('quiz.title') + ' (admin)', href: '/admin/quizzes', icon: '📝', roles: ['admin', 'superadmin'] },
        { label: t('nav.admin'), href: '/admin', icon: '🔧', roles: ['admin', 'superadmin'] },
        { label: t('settings.title'), href: '/settings', icon: '⚙️' },
      ],
    },
  ];

  const hasRole = (roles?: string[]) => {
    if (!roles || !user) return true;
    return roles.some((r) => user.roles?.includes(r));
  };

  return (
    <aside className="w-64 bg-white border-r border-gray-200 flex flex-col h-screen fixed left-0 top-0">
      <div className="p-4 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center text-white font-bold">
            K
          </div>
          <div>
            <div className="font-bold text-gray-900">Kamilya LMS</div>
            <div className="text-xs text-gray-500">AI-платформа обучения</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto p-3 space-y-6">
        {navSections.map((section) => {
          const visibleItems = section.items.filter((item) => hasRole(item.roles));
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.title}>
              <div className="px-3 mb-2 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                {section.title}
              </div>
              <div className="space-y-0.5">
                {visibleItems.map((item) => {
                  const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                  return (
                    <a
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                        isActive
                          ? 'bg-blue-50 text-blue-700 font-medium'
                          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                      }`}
                    >
                      <span className="text-base">{item.icon}</span>
                      {item.label}
                    </a>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      <div className="p-3 border-t border-gray-100">
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center text-sm font-medium text-gray-600">
            {user?.firstName?.[0] || user?.full_name?.[0] || '?'}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-gray-900 truncate">
              {user?.full_name || `${user?.firstName || ''} ${user?.lastName || ''}`}
            </div>
            <div className="text-xs text-gray-500 truncate">
              {user?.roles?.[0] || 'Студент'}
            </div>
          </div>
        </div>
        <button
          onClick={() => {
            logout();
            window.location.href = '/login';
          }}
          className="w-full mt-2 px-3 py-2 text-sm text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors text-left"
        >
          {t('nav.logout')}
        </button>
      </div>
    </aside>
  );
}
