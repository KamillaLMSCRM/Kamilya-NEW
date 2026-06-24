'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { cn } from '@/lib/utils';

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  roles?: string[];
}

function NavLink({ item, isActive, collapsed }: { item: NavItem; isActive: boolean; collapsed: boolean }) {
  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      aria-current={isActive ? 'page' : undefined}
      className={cn(
        'group relative flex items-center rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200',
        collapsed && 'justify-center px-0',
        isActive
          ? 'bg-primary/10 text-primary shadow-sm'
          : 'text-warm-500 hover:bg-warm-100 hover:text-warm-800'
      )}
    >
      <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center', collapsed && 'h-5 w-5')}>
        {item.icon}
      </span>
      {!collapsed && <span className="ml-3 truncate">{item.label}</span>}
      {isActive && (
        <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-primary" aria-hidden="true" />
      )}
    </Link>
  );
}

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { t } = useT();
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  const hasRole = (roles?: string[]) => {
    if (!roles || !user) return true;
    return roles.includes(user.role);
  };

  const navSections: { title: string; items: NavItem[] }[] = [
    {
      title: t('sidebar.generation'),
      items: [
        {
          label: t('nav.aiGeneration'),
          href: '/ai/generate',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z" /><circle cx="12" cy="15" r="2" /></svg>,
          roles: ['admin', 'superadmin', 'org_admin', 'teacher'],
        },
        {
          label: t('nav.documents'),
          href: '/documents',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /></svg>,
          roles: ['admin', 'superadmin', 'org_admin', 'teacher'],
        },
      ],
    },
    {
      title: t('sidebar.courses'),
      items: [
        {
          label: t('nav.courses'),
          href: '/courses',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>,
          roles: ['admin', 'superadmin', 'org_admin', 'teacher'],
        },
        {
          label: t('student.enrolledCourses'),
          href: '/my-courses',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 10v6M2 10l10-5 10 5-10 5z" /><path d="M6 12v5c3 3 6 3 12 0v-5" /></svg>,
          roles: ['student', 'org_admin'],
        },
        {
          label: t('sidebar.myTests'),
          href: '/my-quizzes',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>,
          roles: ['student', 'org_admin'],
        },
        {
          label: t('nav.certificates'),
          href: '/certificates',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="6" /><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" /></svg>,
          roles: ['student', 'org_admin'],
        },
        {
          label: t('nav.positions'),
          href: '/positions',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect width="20" height="14" x="2" y="7" rx="2" ry="2" /><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" /></svg>,
          roles: ['admin', 'superadmin', 'org_admin', 'teacher'],
        },
        {
          label: t('courses.enrollments'),
          href: '/admin/enrollments',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="19" x2="19" y1="8" y2="14" /><line x1="22" x2="16" y1="11" y2="11" /></svg>,
          roles: ['admin', 'superadmin'],
        },
      ],
    },
    {
      title: t('sidebar.admin'),
      items: [
        {
          label: t('nav.userManagement'),
          href: '/admin/users',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>,
          roles: ['admin', 'superadmin'],
        },
        {
          label: `${t('quiz.title')} (admin)`,
          href: '/admin/quizzes',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>,
          roles: ['admin', 'superadmin'],
        },
        {
          label: t('nav.admin'),
          href: '/admin',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>,
          roles: ['admin', 'superadmin'],
        },
        {
          label: t('settings.title'),
          href: '/settings',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><line x1="4" x2="4" y1="21" y2="14" /><line x1="4" x2="4" y1="10" y2="3" /><line x1="12" x2="12" y1="21" y2="12" /><line x1="12" x2="12" y1="8" y2="3" /><line x1="20" x2="20" y1="21" y2="16" /><line x1="20" x2="20" y1="12" y2="3" /></svg>,
          roles: ['admin', 'superadmin'],
        },
      ],
    },
  ];

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-30 flex h-screen flex-col border-r border-warm-200 bg-white transition-all duration-300',
        collapsed ? 'w-[68px]' : 'w-[240px]'
      )}
    >
      {/* Logo */}
      <div className={cn('flex h-16 items-center border-b border-warm-100 px-4', collapsed && 'justify-center px-0')}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-white font-bold text-sm font-display" aria-hidden="true">
          K
        </div>
        {!collapsed && (
          <div className="ml-3 overflow-hidden">
            <div className="text-sm font-bold text-warm-800 font-display truncate">{t('sidebar.logo')}</div>
            <div className="text-[11px] text-warm-400 truncate">{t('sidebar.platform')}</div>
          </div>
        )}
      </div>

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={onToggle}
        className="absolute -right-3 top-20 z-40 flex h-6 w-6 items-center justify-center rounded-full border border-warm-200 bg-white text-warm-400 shadow-sm hover:text-warm-700 hover:border-warm-300 transition-colors"
        title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d={collapsed ? 'm9 18 6-6-6-6' : 'm15 18-6-6 6-6'} />
        </svg>
      </button>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6" aria-label={t('nav.dashboard')}>
        {navSections.map((section) => {
          const visibleItems = section.items.filter((item) => hasRole(item.roles));
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.title}>
              {!collapsed && (
                <div className="px-3 mb-2 text-[10px] font-semibold text-warm-400 uppercase tracking-wider">
                  {section.title}
                </div>
              )}
              <div className="space-y-0.5">
                {visibleItems.map((item) => {
                  const isActive = pathname === item.href || pathname.startsWith(item.href + '/');
                  return <NavLink key={item.href} item={item} isActive={isActive} collapsed={collapsed} />;
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-warm-100 p-3">
        <div className={cn('flex items-center gap-3 rounded-xl px-3 py-2', collapsed && 'justify-center px-0')}>
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
            aria-hidden="true"
          >
            {user?.full_name?.[0] || '?'}
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-warm-800 truncate">
                {user?.full_name || t('common.required' as any)}
              </div>
              <div className="text-[11px] text-warm-400 truncate capitalize">
                {t(`sidebar.userRole.${user?.role}` as any)}
              </div>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            logout();
            router.push('/login');
          }}
          className={cn(
            'mt-1 flex w-full items-center rounded-xl px-3 py-2 text-sm text-warm-400 transition-colors hover:bg-red-50 hover:text-red-600',
            collapsed && 'justify-center px-0'
          )}
          title={collapsed ? t('nav.logout') : undefined}
          aria-label={t('nav.logout')}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" x2="9" y1="12" y2="12" />
          </svg>
          {!collapsed && <span className="ml-3">{t('nav.logout')}</span>}
        </button>
      </div>
    </aside>
  );
}
