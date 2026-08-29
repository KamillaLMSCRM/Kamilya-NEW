import type { TranslationKey } from '@/i18n/useT';

export const APP_ROLES = ['admin', 'methodologist', 'student', 'superadmin'] as const;
export type AppRole = (typeof APP_ROLES)[number];

export const CAPABILITIES = [
  'manage_profile',
  'manage_content',
  'manage_staff',
  'manage_learners',
  'manage_qualifications',
  'manage_assignments',
  'view_training_log',
  'view_training_reports',
  'manage_communications',
  'configure_training_procedures',
  'configure_tenant',
  'manage_accounts',
  'learn',
  'manage_platform',
] as const;
export type Capability = (typeof CAPABILITIES)[number];

export const ROLE_CAPABILITIES: Record<AppRole, readonly Capability[]> = {
  admin: ['manage_profile', 'configure_tenant', 'manage_accounts', 'view_training_reports'],
  methodologist: [
    'manage_profile',
    'manage_content',
    'manage_staff',
    'manage_learners',
    'manage_qualifications',
    'manage_assignments',
    'view_training_log',
    'view_training_reports',
    'manage_communications',
    'configure_training_procedures',
  ],
  student: ['manage_profile', 'learn'],
  superadmin: ['manage_profile', 'manage_platform'],
};

export const ROLE_HOMES: Record<AppRole, string> = {
  admin: '/admin',
  methodologist: '/dashboard',
  student: '/student',
  superadmin: '/admin/super',
};

export const PUBLIC_ROUTE_PREFIXES = [
  '/verify/certificate',
  '/access',
  '/candidate-assessment',
  '/legal',
] as const;

export function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTE_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export type NavigationSection = 'overview' | 'content' | 'workforce' | 'learning' | 'tenant' | 'platform';
export type NavigationIcon =
  | 'dashboard'
  | 'sparkles'
  | 'route'
  | 'users'
  | 'target'
  | 'message'
  | 'book'
  | 'quiz'
  | 'document'
  | 'calendar'
  | 'briefcase'
  | 'assignment'
  | 'certificate'
  | 'settings'
  | 'kiosk'
  | 'log'
  | 'building'
  | 'activity';

type MatchKind = 'exact' | 'prefix' | 'learner-course';

export interface AppRoute {
  id: string;
  href: string;
  capability: Capability;
  match?: MatchKind;
  labelKey?: TranslationKey;
  section?: NavigationSection;
  icon?: NavigationIcon;
  order?: number;
  sidebar?: boolean;
  commandPalette?: boolean;
}

export const ROUTES: readonly AppRoute[] = [
  { id: 'profile', href: '/profile', capability: 'manage_profile', labelKey: 'nav.myProfile' },
  { id: 'methodologist-dashboard', href: '/dashboard', capability: 'manage_content', labelKey: 'nav.dashboard', section: 'overview', icon: 'dashboard', order: 10, sidebar: true, commandPalette: true },
  { id: 'ai-generation', href: '/ai/generate', capability: 'manage_content', match: 'prefix', labelKey: 'nav.aiGeneration', section: 'content', icon: 'sparkles', order: 20, sidebar: true, commandPalette: true },
  { id: 'courses', href: '/courses', capability: 'manage_content', match: 'prefix', labelKey: 'nav.courses', section: 'content', icon: 'book', order: 30, sidebar: true, commandPalette: true },
  { id: 'quizzes', href: '/quizzes', capability: 'manage_content', match: 'prefix', labelKey: 'sidebar.quizConstructor', section: 'content', icon: 'quiz', order: 40, sidebar: true, commandPalette: true },
  { id: 'documents', href: '/documents', capability: 'manage_content', match: 'prefix', labelKey: 'nav.documents', section: 'content', icon: 'document', order: 50, sidebar: true, commandPalette: true },
  { id: 'learning-paths-manage', href: '/learning-paths', capability: 'manage_content', labelKey: 'learningPaths.title', section: 'content', icon: 'route', order: 60, sidebar: true, commandPalette: true },
  { id: 'cohorts', href: '/cohorts', capability: 'manage_staff', labelKey: 'cohorts.title', section: 'workforce', icon: 'users', order: 70, sidebar: true, commandPalette: true },
  { id: 'competencies', href: '/competencies', capability: 'manage_qualifications', labelKey: 'competencies.title', section: 'workforce', icon: 'target', order: 80, sidebar: false, commandPalette: false },
  { id: 'surveys-manage', href: '/surveys', capability: 'manage_communications' },
  { id: 'announcements', href: '/announcements', capability: 'manage_communications' },
  { id: 'staff', href: '/staff?tab=structure', capability: 'manage_staff', labelKey: 'nav.staffSchedule', section: 'workforce', icon: 'users', order: 110, sidebar: true, commandPalette: true },
  { id: 'training-rules', href: '/training-rules?scope=organization', capability: 'manage_staff', labelKey: 'nav.trainingRules', section: 'workforce', icon: 'assignment', order: 112, sidebar: false, commandPalette: false },
  { id: 'training-procedures', href: '/training-procedures', capability: 'configure_training_procedures', labelKey: 'trainingProceduresPage.navLabel', section: 'workforce', icon: 'assignment', order: 113, sidebar: true, commandPalette: true },
  { id: 'training-retention', href: '/training-retention', capability: 'configure_training_procedures', labelKey: 'trainingRetentionPage.navLabel', section: 'workforce', icon: 'assignment', order: 114, sidebar: true, commandPalette: true },
  { id: 'invitations', href: '/invitations', capability: 'manage_learners', labelKey: 'invitations.navLabel', section: 'workforce', icon: 'users', order: 115, sidebar: false, commandPalette: false },
  { id: 'candidate-assessments', href: '/candidate-assessments', capability: 'manage_learners', labelKey: 'nav.candidateAssessments', section: 'workforce', icon: 'users', order: 118, sidebar: true, commandPalette: true },
  { id: 'positions', href: '/positions', capability: 'manage_qualifications', match: 'prefix' },
  { id: 'course-assignments', href: '/assignments', capability: 'manage_assignments', match: 'prefix', labelKey: 'nav.assignmentsAndAccess', section: 'workforce', icon: 'assignment', order: 120, sidebar: true, commandPalette: true },
  { id: 'training-log', href: '/training-log', capability: 'view_training_reports', match: 'prefix', labelKey: 'nav.trainingLog', section: 'overview', icon: 'log', order: 150, sidebar: true, commandPalette: true },

  { id: 'tenant-dashboard', href: '/admin', capability: 'configure_tenant', labelKey: 'nav.admin', section: 'overview', icon: 'dashboard', order: 10, sidebar: true, commandPalette: true },
  { id: 'team', href: '/admin/team', capability: 'manage_accounts', match: 'prefix', labelKey: 'nav.userManagement', section: 'tenant', icon: 'users', order: 20, sidebar: true, commandPalette: true },
  { id: 'users-legacy-surface', href: '/admin/users', capability: 'manage_accounts', match: 'prefix' },
  { id: 'kiosks', href: '/admin/kiosks', capability: 'configure_tenant', match: 'prefix', labelKey: 'nav.kiosks', section: 'tenant', icon: 'kiosk', order: 30, sidebar: true, commandPalette: true },
  { id: 'tenant-settings', href: '/settings', capability: 'configure_tenant', labelKey: 'settings.title', section: 'tenant', icon: 'settings', order: 40, sidebar: true, commandPalette: true },
  { id: 'integrations', href: '/admin/settings/integrations', capability: 'configure_tenant', match: 'prefix', labelKey: 'integrations.title', section: 'tenant', icon: 'settings', order: 50, sidebar: true, commandPalette: true },
  { id: 'certificate-settings', href: '/admin/certificates/settings', capability: 'configure_tenant', match: 'prefix', labelKey: 'sidebar.certificateTemplate', section: 'tenant', icon: 'certificate', order: 60, sidebar: true, commandPalette: true },
  { id: 'audit-log', href: '/admin/audit', capability: 'configure_tenant', match: 'prefix', labelKey: 'nav.auditLog', section: 'tenant', icon: 'log', order: 70, sidebar: true, commandPalette: true },

  { id: 'learner-dashboard', href: '/student', capability: 'learn', labelKey: 'nav.dashboard', section: 'overview', icon: 'dashboard', order: 10, sidebar: true, commandPalette: true },
  { id: 'my-courses', href: '/my-courses', capability: 'learn', labelKey: 'student.enrolledCourses', section: 'learning', icon: 'book', order: 20, sidebar: true, commandPalette: true },
  { id: 'my-quizzes', href: '/my-quizzes', capability: 'learn', labelKey: 'sidebar.myTests', section: 'learning', icon: 'quiz', order: 30, sidebar: true, commandPalette: true },
  { id: 'certificates', href: '/certificates', capability: 'learn', match: 'prefix', labelKey: 'nav.certificates', section: 'learning', icon: 'certificate', order: 40, sidebar: true, commandPalette: true },
  { id: 'learner-course', href: '/courses', capability: 'learn', match: 'learner-course' },
  { id: 'learning-paths-learn', href: '/learning-paths', capability: 'learn' },
  { id: 'surveys-learn', href: '/surveys', capability: 'learn' },

  { id: 'platform', href: '/admin/super', capability: 'manage_platform', match: 'prefix', labelKey: 'superadmin.tenants.title', section: 'platform', icon: 'building', order: 10, sidebar: true, commandPalette: true },
  { id: 'platform-operations', href: '/admin/super/operations', capability: 'manage_platform', match: 'prefix', labelKey: 'superadmin.operations.navLabel', section: 'platform', icon: 'activity', order: 15, sidebar: true, commandPalette: true },
  { id: 'providers', href: '/admin/providers', capability: 'manage_platform', match: 'prefix', labelKey: 'providers.title', section: 'platform', icon: 'settings', order: 20, sidebar: true, commandPalette: true },
];

export const LEGACY_ROUTES: readonly Pick<AppRoute, 'href' | 'capability' | 'match'>[] = [
  { href: '/admin/staff', capability: 'manage_staff', match: 'prefix' },
  { href: '/admin/invitations', capability: 'manage_learners', match: 'prefix' },
  { href: '/admin/training-log', capability: 'view_training_reports', match: 'prefix' },
  { href: '/admin/quizzes/assign', capability: 'manage_content', match: 'prefix' },
  { href: '/admin/enrollments', capability: 'manage_assignments', match: 'prefix' },
];

export function isAppRole(role: string | null | undefined): role is AppRole {
  return typeof role === 'string' && (APP_ROLES as readonly string[]).includes(role);
}

export function hasCapability(role: string | null | undefined, capability: Capability): boolean {
  return isAppRole(role) && ROLE_CAPABILITIES[role].includes(capability);
}

function routeMatches(route: Pick<AppRoute, 'href' | 'match'>, pathname: string): boolean {
  const target = new URL(route.href, 'http://localhost').pathname;
  if (route.match === 'learner-course') {
    return pathname.startsWith('/courses/') && !pathname.includes('/edit');
  }
  if (route.match === 'prefix') return pathname === target || pathname.startsWith(`${target}/`);
  return pathname === target;
}

export function canAccessRegisteredRoute(role: string | null | undefined, pathname: string): boolean {
  return [...ROUTES, ...LEGACY_ROUTES].some(
    (route) => routeMatches(route, pathname) && hasCapability(role, route.capability),
  );
}

export function getNavigationRoutes(role: string | null | undefined, surface: 'sidebar' | 'commandPalette') {
  return ROUTES
    .filter((route) => route[surface] && hasCapability(role, route.capability))
    .toSorted((a, b) => (a.order ?? 0) - (b.order ?? 0));
}
