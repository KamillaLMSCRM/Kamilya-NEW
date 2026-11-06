import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, resolve, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Executable whole-LMS visual coverage map.
 *
 * Every canonical page must be classified once: redesigned with a real page
 * composition (directly or through one canonical owner), a redirect/alias, an
 * explicitly deferred administrator screen, or a retained non-product example.
 * A marker alone is not proof, but an unclassified page can no longer disappear
 * from the acceptance claim.
 */

const appRoot = resolve(process.cwd(), 'src/app');
const NON_PRODUCT = new Set(['login/example']);

type Entry = { status: 'redesigned' | 'alias' | 'deferred' | 'example'; owner?: string };

const coverage: Record<string, Entry> = {
  '': { status: 'alias', owner: 'app/login/page.tsx' },
  'accept-invite': { status: 'redesigned' },
  'access/[token]': { status: 'redesigned' },
  'announcements': { status: 'redesigned' },
  'candidate-assessment/[token]': { status: 'redesigned' },
  'candidate-assessments': { status: 'redesigned' },
  'certificates': { status: 'redesigned' },
  'cohorts': { status: 'redesigned' },
  'competencies': { status: 'redesigned' },
  'course-review': { status: 'redesigned' },
  'course-review-access/[token]': { status: 'redesigned' },
  'course-review-access/review': { status: 'redesigned' },
  'course-review-access/review/requests/[requestId]': { status: 'redesigned' },
  'course-review-requests/[requestId]': { status: 'alias', owner: 'components/course-approval/ReviewRequestScreen.tsx' },
  'courses': { status: 'redesigned' },
  'courses/[id]': { status: 'redesigned' },
  'courses/[id]/edit': { status: 'redesigned' },
  'courses/quiz/[quizId]': { status: 'redesigned' },
  'courses/quiz/[quizId]/preview': { status: 'redesigned' },
  'courses/templates/[blueprintId]': { status: 'redesigned' },
  'dashboard': { status: 'alias', owner: 'features/dashboard/MethodologistDashboard.tsx' },
  'documents': { status: 'redesigned' },
  'documents/[id]/editorial-review': { status: 'alias', owner: 'features/source-editorial-review/SourceEditorialReview.tsx' },
  'documents/[id]/editorial-review/[approvalId]': { status: 'alias', owner: 'features/source-editorial-review/SourceEditorialReview.tsx' },
  'kiosk/[token]': { status: 'redesigned' },
  'learning-cycles': { status: 'redesigned' },
  'learning-paths': { status: 'redesigned' },
  'login': { status: 'redesigned' },
  'login/demo': { status: 'redesigned' },
  'login/example': { status: 'example' },
  'mandatory-training': { status: 'redesigned' },
  'methodologist-workbench': { status: 'redesigned' },
  'my-courses': { status: 'redesigned' },
  'my-quizzes': { status: 'redesigned' },
  'positions': { status: 'redesigned' },
  'positions/[positionId]': { status: 'alias', owner: 'features/positions/PositionQualificationCard.tsx' },
  'profile': { status: 'redesigned' },
  'quizzes': { status: 'redesigned' },
  'staff': { status: 'alias', owner: 'app/admin/staff/page.tsx' },
  'student': { status: 'redesigned' },
  'surveys': { status: 'redesigned' },
  'training-log': { status: 'alias', owner: 'app/admin/training-log/page.tsx' },
  'training-procedures': { status: 'alias', owner: 'features/training-procedures/TrainingProceduresPage.tsx' },
  'training-retention': { status: 'alias', owner: 'features/training-retention/TrainingRetentionPage.tsx' },
  'training-rules': { status: 'alias', owner: 'features/training-rules/TrainingRulesPage.tsx' },
  'verify/certificate': { status: 'alias', owner: 'app/verify/certificate/VerificationPanel.tsx' },
  'verify/certificate/[number]': { status: 'alias', owner: 'app/verify/certificate/VerificationPanel.tsx' },
  'legal/privacy': { status: 'alias', owner: 'components/legal/LegalDocument.tsx' },
  'legal/privacy/kk': { status: 'alias', owner: 'components/legal/LegalDocument.tsx' },
  'legal/terms': { status: 'alias', owner: 'components/legal/LegalDocument.tsx' },
  'legal/terms/kk': { status: 'alias', owner: 'components/legal/LegalDocument.tsx' },
  'register': { status: 'alias', owner: 'app/register-tenant/page.tsx' },
  'register-tenant': { status: 'redesigned' },
  'invitations': { status: 'alias', owner: 'app/admin/invitations/page.tsx' },
  'admin/staff': { status: 'redesigned' },
  'admin/invitations': { status: 'redesigned' },
  'admin/training-log': { status: 'redesigned' },
  'admin/enrollments': { status: 'alias', owner: 'features/course-assignments/CourseAssignmentsPage.tsx' },
  'admin/quizzes': { status: 'alias', owner: 'app/quizzes/page.tsx' },
  'admin/quizzes/assign': { status: 'alias', owner: 'app/quizzes/page.tsx' },
  'assignments': { status: 'alias', owner: 'features/course-assignments/CourseAssignmentsPage.tsx' },
  'ai/generate': { status: 'redesigned' },
  'admin/super': { status: 'deferred' },
  'admin/super/operations': { status: 'deferred' },
  'admin/super/tenants': { status: 'deferred' },
  'admin/super/tenants/[id]': { status: 'deferred' },
  'superadmin/login': { status: 'deferred' },
  'admin': { status: 'deferred' },
  'admin/audit': { status: 'deferred' },
  'admin/certificates/settings': { status: 'deferred' },
  'admin/course-approvals': { status: 'deferred' },
  'admin/employees': { status: 'alias', owner: 'app/admin/staff/page.tsx' },
  'admin/kiosks': { status: 'deferred' },
  'admin/providers': { status: 'deferred' },
  'admin/settings/ai': { status: 'deferred' },
  'admin/settings/integrations': { status: 'deferred' },
  'admin/team': { status: 'deferred' },
  'admin/training-evidence/settings': { status: 'deferred' },
  'admin/users': { status: 'deferred' },
  'settings': { status: 'deferred' },
};

function discoverPages(directory = appRoot): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return discoverPages(path);
    return name === 'page.tsx' ? [relative(appRoot, directory).split(sep).join('/')] : [];
  });
}

function read(relativePath: string) {
  return readFileSync(resolve(process.cwd(), 'src', relativePath), 'utf8');
}

const MARKER = /WorkspacePage|PublicWorkspace|data-redesign-page|data-catalog-layout="workspace-v1"/;

describe('whole LMS redesign coverage', () => {
  it('classifies every discovered canonical page exactly once', () => {
    const discovered = discoverPages().sort();
    const classified = Object.keys(coverage).sort();
    expect(discovered).toEqual(classified);
    expect(new Set(classified).size).toBe(classified.length);
  });

  it('redesigned and alias owners contain a real WorkspacePage/PublicWorkspace composition', () => {
    const failures = Object.entries(coverage).flatMap(([route, entry]) => {
      if (entry.status !== 'redesigned' && entry.status !== 'alias') return [];
      const file = entry.owner ?? `app/${route}/page.tsx`;
      return MARKER.test(read(file)) ? [] : [`${route} -> ${file}`];
    });
    expect(failures).toEqual([]);
  });

  it('keeps the deferred admin/superadmin family free of partial redesign claims', () => {
    for (const [route, entry] of Object.entries(coverage)) {
      if (entry.status !== 'deferred') continue;
      const source = read(`app/${route}/page.tsx`);
      expect(source, `${route} should stay deferred until explicitly re-authorized`).not.toMatch(MARKER);
    }
  });

  it('retains the non-product example without counting it as redesigned LMS UI', () => {
    expect(NON_PRODUCT.has('login/example')).toBe(true);
    expect(coverage['login/example'].status).toBe('example');
  });
});
