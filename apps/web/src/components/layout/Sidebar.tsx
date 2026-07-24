'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
  Award,
  BookOpen,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  ClipboardCheck,
  FileText,
  GraduationCap,
  LayoutDashboard,
  LogOut,
  Map,
  MessageSquare,
  Monitor,
  MoreHorizontal,
  Route,
  Settings,
  Sparkles,
  Target,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { useAuthStore } from '@/store/authStore';
import { useT, type TranslationKey } from '@/i18n/useT';
import { cn } from '@/lib/utils';
import { Logo } from '@/components/brand/Logo';
import { isNavigationItemActive } from '@/lib/rolePolicy';
import {
  getNavigationRoutes,
  type NavigationIcon,
  type NavigationSection,
} from '@/lib/routeRegistry';

const SECTION_LABELS: Record<NavigationSection, TranslationKey> = {
  overview: 'sidebar.overview',
  content: 'sidebar.content',
  workforce: 'sidebar.workforce',
  learning: 'sidebar.learning',
  tenant: 'sidebar.tenant',
  platform: 'superadmin.title',
};

const ICONS: Record<NavigationIcon, LucideIcon> = {
  dashboard: LayoutDashboard,
  sparkles: Sparkles,
  route: Route,
  users: Users,
  target: Target,
  message: MessageSquare,
  book: BookOpen,
  quiz: ClipboardCheck,
  document: FileText,
  calendar: CalendarDays,
  briefcase: BriefcaseBusiness,
  assignment: GraduationCap,
  certificate: Award,
  settings: Settings,
  kiosk: Monitor,
  log: Map,
  building: Building2,
};

interface SidebarProps {
  collapsed: boolean;
  mobileOpen?: boolean;
  onToggle: () => void;
  onClose?: () => void;
}

export default function Sidebar({ collapsed, mobileOpen = false, onToggle, onClose }: SidebarProps) {
  const { t } = useT();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const routes = getNavigationRoutes(user?.role, 'sidebar');
  const sections = [...new Set(routes.map((route) => route.section).filter(Boolean))] as NavigationSection[];

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 z-30 flex h-screen flex-col border-r border-border bg-card transition-all duration-300',
        collapsed ? 'w-[68px]' : 'w-[240px]',
        'max-md:w-[240px] max-md:shadow-card-lg',
        mobileOpen ? 'max-md:translate-x-0' : 'max-md:-translate-x-full',
      )}
    >
      <div className={cn('flex h-16 items-center border-b border-border px-4', collapsed && 'justify-center px-0')}>
        <div className={cn('min-w-0', collapsed && 'flex justify-center')}>
          <Logo variant={collapsed ? 'mark' : 'full'} size={32} withSubtitle={!collapsed} />
        </div>
      </div>

      <button
        type="button"
        onClick={onToggle}
        className="absolute -right-3 top-20 z-40 hidden h-10 w-10 items-center justify-center rounded-full border border-border bg-card text-muted-foreground shadow-sm transition-colors hover:text-foreground md:flex"
        title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        aria-expanded={!collapsed}
        aria-controls="sidebar-nav"
      >
        <MoreHorizontal className="h-4 w-4" aria-hidden />
      </button>
      <button
        type="button"
        onClick={onClose}
        className="absolute right-3 top-5 z-40 flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground md:hidden"
        aria-label={t('sidebar.close')}
        title={t('sidebar.close')}
      >
        <span aria-hidden>×</span>
      </button>

      <nav id="sidebar-nav" className="flex-1 space-y-6 overflow-y-auto px-3 py-4" aria-label={t('a11y.mainNavigation')}>
        {sections.map((section) => (
          <div key={section}>
            {!collapsed && (
              <h2 className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {t(SECTION_LABELS[section])}
              </h2>
            )}
            <ul className="space-y-0.5" role="list">
              {routes.filter((route) => route.section === section).map((route) => {
                const Icon = ICONS[route.icon!];
                const label = t(route.labelKey!);
                const active = isNavigationItemActive(route.href, pathname, searchParams);
                return (
                  <li key={route.id}>
                    <Link
                      href={route.href}
                      onClick={onClose}
                      title={label}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'group relative flex items-center rounded-xl px-3 py-2.5 text-sm font-medium transition-colors',
                        collapsed && 'justify-center px-0',
                        active ? 'bg-primary/10 text-primary shadow-sm' : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                      )}
                    >
                      <Icon className="h-5 w-5 shrink-0" aria-hidden />
                      {!collapsed && <span className="ml-3 truncate">{label}</span>}
                      {active && <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r bg-primary" aria-hidden />}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border p-3">
        <div className={cn('flex items-center gap-3 rounded-xl px-3 py-2', collapsed && 'justify-center px-0')}>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary" aria-hidden>
            {user?.full_name?.[0] || '?'}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-foreground">{user?.full_name || t('common.required')}</div>
              <div className="truncate text-[11px] capitalize text-muted-foreground">
                {t(`sidebar.userRole.${user?.role}` as TranslationKey)}
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
            isLoggingOut && 'pointer-events-none opacity-60',
          )}
          title={collapsed ? t('nav.logout') : undefined}
          aria-label={t('nav.logout')}
        >
          <LogOut className="h-[18px] w-[18px]" aria-hidden />
          {!collapsed && <span className="ml-3">{t('nav.logout')}</span>}
        </button>
      </div>
    </aside>
  );
}
