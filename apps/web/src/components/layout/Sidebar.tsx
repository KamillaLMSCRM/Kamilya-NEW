'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/authStore';
import { useT } from '@/i18n/useT';
import { cn } from '@/lib/utils';
import { Logo } from '@/components/brand/Logo';

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
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
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
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  const hasRole = (roles?: string[]) => {
    if (!roles || !user) return true;
    return roles.includes(user.role);
  };

  // Navigation structure reorganized on 2026-06-27:
  // - "Контент" — creating course/test/document content (was "Курсы" + "Генерация" mixed)
  // - "Персонал" — staff/staff-tree/positions/enrollments operations
  //   (was hidden under /admin/* with no sidebar entries, so methodologists
  //    couldn't find them; now grouped together since they form one workflow)
  // - "Админ" — platform administration (unchanged)
  const navSections: { title: string; items: NavItem[] }[] = [
    {
      title: t('sidebar.content'),
      items: [
        {
          label: t('nav.aiGeneration'),
          href: '/ai/generate',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 2a4 4 0 0 0-4 4v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2h-2V6a4 4 0 0 0-4-4Z" /><circle cx="12" cy="15" r="2" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
        {
          label: t('nav.courses'),
          href: '/courses',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
        {
          // Quiz constructor. Was previously labelled "Тест — Админ" and felt
          // out of place. Renamed to "Конструктор тестов" via page header on
          // 2026-06-27. AI-assist section is now hidden until a lesson is
          // picked, so it stops looking like "AI from thin air".
          label: t('sidebar.quizConstructor'),
          href: '/quizzes',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
        {
          label: t('nav.documents'),
          href: '/documents',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path d="M14 2v4a2 2 0 0 0 2 2h4" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
      ],
    },
    {
      // "Управление курсами" section. The course-assignment workflow
      // lives inside "Штатное расписание" (4 tabs: Импорт / Структура /
      // Привязка курсов / Курсы компании). Direct user→course assignment
      // (level-4 manual override) lives at its own URL. See
      // TZ_COURSE_ASSIGNMENT_ACCESS_v1 §1.1 for the 4-level model.
      //
      // 2026-06-30: removed the duplicated "Привязка курсов" and
      // "Курсы компании" sidebar entries — they deep-linked into
      // /admin/staff?tab=... which is the same place the
      // "Штатное расписание" entry already points to. Renamed
      // "Штатка" → "Штатное расписание" to match the page header.
      title: t('sidebar.courseManagement'),
      items: [
        {
          // Staff schedule ("Штатное расписание"). Page header reads the
          // same; we use the full wording here so the sidebar entry
          // doesn't look like a nickname. ?tab=structure deep-links
          // into the org-chart tab, not the importer.
          label: t('nav.staffSchedule'),
          href: '/staff?tab=structure',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
        {
          // Positions — JD authoring with AI tools (analyze, suggest courses,
          // onboarding quiz). Bridge between staff roster and course content.
          label: t('nav.positions'),
          href: '/positions',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect width="20" height="14" x="2" y="7" rx="2" ry="2" /><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" /></svg>,
          roles: ['admin', 'org_admin', 'teacher'],
        },
        {
          // Direct user→course assignment (level-4 manual override).
          // ADR-0012 keeps this shared between admin and methodologist
          // (teacher) — content domain, not pure tenant infrastructure.
          label: t('courses.enrollments'),
          href: '/assignments',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="19" x2="19" y1="8" y2="14" /><line x1="22" x2="16" y1="11" y2="11" /></svg>,
          roles: ['methodologist', 'teacher'],
        },
        {
          label: t('sidebar.certificateTemplate'),
          href: '/admin/certificates/settings',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="6" /><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" /></svg>,
          roles: ['admin', 'org_admin'],
        },
      ],
    },
    {
      // Student-facing shortcuts kept here so org_admin (who often acts
      // as both methodologist and student in demo tenants) can switch
      // perspective without logout. Unchanged from prior version.
      title: t('sidebar.learning'),
      items: [
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
      ],
    },
    {
      title: t('sidebar.admin'),
      items: [
        {
          // ADR-0011: team-management surface (teacher/admin/org_admin only —
          // students are auto-provisioned via Telegram-bot or staff import).
          // Was at /admin/users; renamed to /admin/team with the student
          // exclusion enforced server-side.
          label: t('nav.userManagement'),
          href: '/admin/team',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></svg>,
          roles: ['admin', 'org_admin'],
        },
        {
          label: t('nav.admin'),
          href: '/admin',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" /><circle cx="12" cy="12" r="3" /></svg>,
          roles: ['admin', 'org_admin'],
        },
        {
          label: t('nav.kiosks'),
          href: '/admin/kiosks',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8" /><path d="M12 16v4" /></svg>,
          roles: ['admin', 'org_admin'],
        },
        {
          // P0.3 first-tenant hardening. Unified training log — native + SCORM
          // courses in one view. HR/owner can answer «кто не прошёл обязательный
          // курс» и выгрузить CSV. Hidden from teacher/student because it's an
          // admin/HR concern (ADR-0012).
          label: t('nav.trainingLog'),
          href: '/admin/training-log',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="9" y1="13" x2="15" y2="13" /><line x1="9" y1="17" x2="15" y2="17" /></svg>,
          roles: ['admin', 'org_admin', 'methodologist'],
        },
        {
          label: t('settings.title'),
          href: '/settings',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><line x1="4" x2="4" y1="21" y2="14" /><line x1="4" x2="4" y1="10" y2="3" /><line x1="12" x2="12" y1="21" y2="12" /><line x1="12" x2="12" y1="8" y2="3" /><line x1="20" x2="20" y1="21" y2="16" /><line x1="20" x2="20" y1="12" y2="3" /></svg>,
          roles: ['admin', 'org_admin'],
        },
        {
label: t('providers.title'),
           href: '/admin/providers',
           icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 2 4 7v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V7l-8-5z" /><path d="m9 12 2 2 4-4" /></svg>,
           roles: ['superadmin'],
         },
         {
           // Notification channels (SMTP/Telegram/WhatsApp) — owned by tenant
           // (ADR-0010). Admin and org_admin see it because they configure the
           // channels; superadmin sees it as well to help onboard large tenants.
           label: t('integrations.title'),
           href: '/admin/settings/integrations',
           icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 12h-4l-3 9L9 3l-3 9H2" /></svg>,
           roles: ['admin', 'org_admin', 'superadmin'],
        },
      ],
    },
    {
      title: t('superadmin.title'),
      items: [
        {
          label: t('superadmin.tenants.title'),
          href: '/admin/super/tenants',
          icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 21h18" /><path d="M5 21V7l8-4v18" /><path d="M19 21V11l-6-4" /><path d="M9 9v.01" /><path d="M9 12v.01" /><path d="M9 15v.01" /><path d="M9 18v.01" /></svg>,
          roles: ['superadmin'],
        },
      ],
    },
  ];

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-30 flex h-screen flex-col border-r border-border bg-card transition-all duration-300',
        collapsed ? 'w-[68px]' : 'w-[240px]'
      )}
    >
      {/* Logo */}
      <div
        className={cn('flex h-16 items-center border-b border-border px-4', collapsed && 'justify-center px-0')}
      >
        <div className={cn('min-w-0', collapsed && 'flex justify-center')}>
          <Logo variant={collapsed ? 'mark' : 'full'} size={32} withSubtitle={!collapsed} />
        </div>
      </div>

      {/* Collapse toggle */}
      <button
        type="button"
        onClick={onToggle}
        className="absolute -right-3 top-20 z-40 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm hover:text-foreground hover:border-border transition-colors"
        title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-expanded={!collapsed}
        aria-controls="sidebar-nav"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d={collapsed ? 'm9 18 6-6-6-6' : 'm15 18-6-6 6-6'} />
        </svg>
      </button>

      {/* Nav */}
      <nav
        id="sidebar-nav"
        className="flex-1 overflow-y-auto px-3 py-4 space-y-6"
        aria-label={t('a11y.mainNavigation')}
      >
        {navSections.map((section) => {
          const visibleItems = section.items.filter((item) => hasRole(item.roles));
          if (visibleItems.length === 0) return null;

          return (
            <div key={section.title}>
              {!collapsed && (
                <h2 className="px-3 mb-2 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {section.title}
                </h2>
              )}
              <ul className="space-y-0.5" role="list">
                {visibleItems.map((item) => {
                  // Active when pathname exactly matches OR when the item
                  // path is a single segment and pathname has it as its
                  // first segment. We deliberately don't treat a 1-segment
                  // href like `/admin` as a prefix of `/admin/staff` so
                  // the parent "Админ" link doesn't light up while the user
                  // is on a child page like `/admin/staff`. Otherwise a
                  // tenant-admin would see two highlighted items at once.
                  const isActive =
                    pathname === item.href ||
                    (item.href.split('/').filter(Boolean).length > 1 &&
                      pathname.startsWith(item.href + '/'));
                  return (
                    <li key={item.href}>
                      <NavLink item={item} isActive={isActive} collapsed={collapsed} />
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-border p-3">
        <div className={cn('flex items-center gap-3 rounded-xl px-3 py-2', collapsed && 'justify-center px-0')}>
          <div
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
            aria-hidden="true"
          >
            {user?.full_name?.[0] || '?'}
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-foreground truncate">
                {user?.full_name || t('common.required' as any)}
              </div>
              <div className="text-[11px] text-muted-foreground truncate capitalize">
                {t(`sidebar.userRole.${user?.role}` as any)}
              </div>
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={async () => {
            if (isLoggingOut) return;
            setIsLoggingOut(true);
            try {
              await logout();
            } finally {
              router.replace('/login');
            }
          }}
          disabled={isLoggingOut}
          className={cn(
            'mt-1 flex w-full items-center rounded-xl px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive',
            collapsed && 'justify-center px-0',
            isLoggingOut && 'pointer-events-none opacity-60'
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
