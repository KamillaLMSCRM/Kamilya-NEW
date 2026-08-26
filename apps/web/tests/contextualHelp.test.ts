import { describe, expect, it } from 'vitest';

import { CONTEXTUAL_HELP_TOPIC_IDS, getContextualHelp } from '@/lib/contextualHelp';

const METHODOLOGIST_PATHS = [
  '/dashboard',
  '/ai/generate',
  '/courses',
  '/quizzes',
  '/documents',
  '/learning-paths',
  '/cohorts',
  '/staff',
  '/training-procedures',
  '/training-retention',
  '/candidate-assessments',
  '/assignments',
  '/training-log',
];

describe('contextual help registry', () => {
  it('covers every primary methodologist menu section', () => {
    expect(CONTEXTUAL_HELP_TOPIC_IDS).toHaveLength(14);
    for (const path of METHODOLOGIST_PATHS) {
      const help = getContextualHelp(path, 'methodologist', 'ru');
      expect(help, path).not.toBeNull();
      expect(help?.steps).toHaveLength(3);
      expect(help?.example.length).toBeGreaterThan(20);
    }
  });

  it('resolves nested pages and localized content', () => {
    expect(getContextualHelp('/courses/course-123/edit', 'methodologist', 'kk')?.title).toBe('Курстар');
    expect(getContextualHelp('/learning-paths/path-123', 'methodologist', 'en')?.title).toBe('Learning programs');
  });

  it('does not expose role-inappropriate help', () => {
    expect(getContextualHelp('/admin/team', 'methodologist', 'ru')).toBeNull();
    expect(getContextualHelp('/courses', 'admin', 'ru')).toBeNull();
    expect(getContextualHelp('/admin/team', 'admin', 'ru')?.id).toBe('team');
  });

  it('falls back to Russian for an unsupported locale', () => {
    expect(getContextualHelp('/documents', 'methodologist', 'de')?.title).toBe('Документы');
  });
});
