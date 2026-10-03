import { describe, expect, it } from 'vitest';

import { CONTEXTUAL_HELP_TOPIC_IDS, getContextualHelp } from '@/lib/contextualHelp';

const METHODOLOGIST_PATHS = [
  '/dashboard',
  '/ai/generate',
  '/courses',
  '/quizzes',
  '/documents',
  '/learning-paths',
  '/learning-cycles',
  '/cohorts',
  '/staff',
  '/training-procedures',
  '/training-retention',
  '/candidate-assessments',
  '/assignments',
  '/mandatory-training',
  '/training-log',
];

describe('contextual help registry', () => {
  it('covers every primary methodologist menu section', () => {
    for (const path of METHODOLOGIST_PATHS) {
      const help = getContextualHelp(path, 'methodologist', 'ru');
      expect(help, path).not.toBeNull();
      expect(help?.steps).toHaveLength(3);
      expect(help?.example.length).toBeGreaterThan(20);
    }
  });

  it('maps each declared role surface to a role-specific topic', () => {
    const expected: Array<[string, string, string]> = [
      ['/methodologist-workbench', 'methodologist', 'methodologist-workbench'],
      ['/competencies', 'methodologist', 'competencies'],
      ['/training-rules', 'methodologist', 'training-rules'],
      ['/positions/position-1', 'methodologist', 'positions'],
      ['/profile', 'admin', 'profile'],
      ['/profile', 'methodologist', 'profile'],
      ['/profile', 'student', 'profile'],
      ['/profile', 'superadmin', 'profile'],
      ['/student', 'student', 'student-dashboard'],
      ['/my-courses', 'student', 'student-my-courses'],
      ['/my-quizzes', 'student', 'student-my-quizzes'],
      ['/certificates', 'student', 'student-certificates'],
      ['/learning-paths', 'student', 'student-learning-paths'],
      ['/courses/course-1', 'student', 'student-course'],
      ['/admin', 'admin', 'admin-dashboard'],
      ['/settings', 'admin', 'admin-settings'],
      ['/admin/settings/integrations', 'admin', 'admin-integrations'],
      ['/admin/settings/ai', 'admin', 'admin-ai'],
      ['/admin/certificates/settings', 'admin', 'admin-certificates'],
      ['/admin/training-evidence/settings', 'admin', 'admin-training-evidence'],
      ['/admin/audit', 'admin', 'admin-audit'],
      ['/admin/kiosks', 'admin', 'admin-kiosks'],
      ['/admin/course-approvals', 'admin', 'admin-course-approvals'],
      ['/admin/course-approvals', 'methodologist', 'admin-course-approvals'],
      ['/invitations', 'methodologist', 'invitations'],
      ['/training-log', 'admin', 'admin-training-reports'],
      ['/mandatory-training', 'admin', 'admin-training-reports'],
      ['/admin/super', 'superadmin', 'superadmin'],
      ['/admin/super/operations', 'superadmin', 'superadmin-operations'],
      ['/admin/providers', 'superadmin', 'superadmin-providers'],
    ];
    for (const [path, role, id] of expected) {
      expect(getContextualHelp(path, role, 'ru')?.id, `${role} ${path}`).toBe(id);
    }
    expect(CONTEXTUAL_HELP_TOPIC_IDS).toEqual(expect.arrayContaining(expected.map(([, , id]) => id)));
  });

  it('prefers the most-specific topic and keeps student courses separate', () => {
    expect(getContextualHelp('/admin/course-approvals/course-1', 'admin', 'ru')?.id).toBe('admin-course-approvals');
    expect(getContextualHelp('/admin/settings/ai', 'admin', 'ru')?.id).toBe('admin-ai');
    expect(getContextualHelp('/courses/course-1/edit', 'methodologist', 'ru')?.id).toBe('courses');
    expect(getContextualHelp('/courses/course-1', 'student', 'ru')?.id).toBe('student-course');
  });

  it('keeps every topic complete in all supported locales', () => {
    const cases: Array<[string, string]> = [
      ['/dashboard', 'methodologist'], ['/ai/generate', 'methodologist'], ['/courses', 'methodologist'],
      ['/quizzes', 'methodologist'], ['/documents', 'methodologist'], ['/learning-paths', 'methodologist'],
      ['/learning-cycles', 'methodologist'], ['/cohorts', 'methodologist'], ['/staff', 'methodologist'],
      ['/training-procedures', 'methodologist'], ['/training-retention', 'methodologist'],
      ['/candidate-assessments', 'methodologist'], ['/assignments', 'methodologist'],
      ['/mandatory-training', 'methodologist'], ['/training-log', 'methodologist'],
      ['/admin/team', 'admin'], ['/methodologist-workbench', 'methodologist'], ['/positions/position-1', 'methodologist'],
      ['/competencies', 'methodologist'], ['/training-rules', 'methodologist'],
      ['/profile', 'student'], ['/student', 'student'], ['/my-courses', 'student'], ['/my-quizzes', 'student'],
      ['/certificates', 'student'], ['/learning-paths', 'student'], ['/courses/course-1', 'student'],
      ['/admin', 'admin'], ['/settings', 'admin'], ['/admin/settings/integrations', 'admin'],
      ['/admin/settings/ai', 'admin'], ['/admin/certificates/settings', 'admin'],
      ['/admin/training-evidence/settings', 'admin'], ['/admin/audit', 'admin'], ['/admin/kiosks', 'admin'],
      ['/admin/course-approvals', 'admin'], ['/training-log', 'admin'], ['/mandatory-training', 'admin'],
      ['/admin/course-approvals', 'methodologist'], ['/invitations', 'methodologist'],
      ['/admin/super', 'superadmin'], ['/admin/super/operations', 'superadmin'], ['/admin/providers', 'superadmin'],
    ];
    for (const [path, role] of cases) {
      for (const locale of ['ru', 'kk', 'en']) {
        const help = getContextualHelp(path, role, locale);
        expect(help, `${role} ${path}/${locale}`).not.toBeNull();
        expect(help?.title).toBeTruthy();
        expect(help?.purpose).toBeTruthy();
        expect(help?.steps).toHaveLength(3);
        expect(help?.steps.every(Boolean)).toBe(true);
        expect(help?.example).toBeTruthy();
        expect(help?.result).toBeTruthy();
        expect(help?.important).toBeTruthy();
      }
    }
  });

  it('resolves nested pages and localized content', () => {
    expect(getContextualHelp('/courses/course-123/edit', 'methodologist', 'kk')?.title).toBe('Курстар');
    expect(getContextualHelp('/learning-paths/path-123', 'methodologist', 'en')?.title).toBe('Learning programs');
    expect(getContextualHelp('/ai/generate', 'methodologist', 'ru')?.title).toBe('Создать курс из материалов');
    expect(getContextualHelp('/quizzes', 'methodologist', 'ru')?.title).toBe('Тесты и вопросы');
    expect(getContextualHelp('/candidate-assessments', 'methodologist', 'ru')?.title).toBe('Тестирование кандидатов');
    expect(getContextualHelp('/training-procedures', 'methodologist', 'ru')?.title).toBe('Подтверждение обучения');
    expect(getContextualHelp('/training-retention', 'methodologist', 'ru')?.title).toBe('Сроки хранения результатов');
    expect(getContextualHelp('/learning-cycles', 'methodologist', 'ru')?.title).toBe('Циклы обучения');
    expect(getContextualHelp('/mandatory-training', 'methodologist', 'ru')?.title).toBe('Обязательное обучение');
  });

  it('does not expose role-inappropriate help', () => {
    expect(getContextualHelp('/admin/team', 'methodologist', 'ru')).toBeNull();
    expect(getContextualHelp('/courses', 'admin', 'ru')).toBeNull();
    expect(getContextualHelp('/admin/team', 'admin', 'ru')?.id).toBe('team');
    expect(getContextualHelp('/admin', 'methodologist', 'ru')).toBeNull();
    expect(getContextualHelp('/student', 'admin', 'ru')).toBeNull();
    expect(getContextualHelp('/admin/super', 'student', 'ru')).toBeNull();
  });

  it('matches dashboard headings in all locales', () => {
    expect(getContextualHelp('/dashboard', 'methodologist', 'ru')?.title).toBe('Обзор обучения');
    expect(getContextualHelp('/dashboard', 'methodologist', 'kk')?.title).toBe('Оқу шолуы');
    expect(getContextualHelp('/dashboard', 'methodologist', 'en')?.title).toBe('Learning overview');
  });

  it('describes the source-backed controls without invented workflow steps', () => {
    const workbench = getContextualHelp('/methodologist-workbench', 'methodologist', 'ru');
    expect(workbench?.steps.join(' ')).toContain('команду назначения');
    expect(workbench?.steps.join(' ')).toContain('предварительный просмотр');
    expect(workbench?.result).toContain('квитанция');
    expect(workbench?.steps.join(' ')).not.toContain('список действий');

    expect(getContextualHelp('/positions', 'methodologist', 'ru')?.title).toBe('Должности');

    const candidate = getContextualHelp('/candidate-assessments', 'methodologist', 'ru');
    expect(candidate?.steps.join(' ')).toContain('опубликованный курс');
    expect(candidate?.steps.join(' ')).toContain('персональную ссылку и PIN');
    expect(candidate?.steps.join(' ')).not.toContain('Выберите должность');

    const approvals = getContextualHelp('/admin/course-approvals', 'admin', 'ru');
    expect(approvals?.steps[2]).toContain('статусы запросов');
    expect(approvals?.example).not.toContain('предпросмотр');
    expect(getContextualHelp('/admin/course-approvals', 'methodologist', 'ru')?.example).toContain('администратор тенанта');

    const cycles = getContextualHelp('/learning-cycles', 'methodologist', 'ru');
    expect(cycles?.steps[1]).toContain('периодичность программы');
    expect(getContextualHelp('/cohorts', 'methodologist', 'ru')?.steps[2]).toContain('аудиторию');

    const assignment = getContextualHelp('/assignments', 'methodologist', 'ru');
    expect(assignment?.steps[1]).toContain('первого входа');
    expect(assignment?.steps[1]).toContain('абсолютный срок');
  });

  it('keeps invitations truthful and role-scoped', () => {
    const help = getContextualHelp('/invitations', 'methodologist', 'ru');
    expect(help?.title).toBe('Приглашения сотрудников');
    expect(help?.steps.join(' ')).toContain('не сбрасывает пароль');
    expect(help?.example).toContain('демо-режиме');
    expect(getContextualHelp('/invitations', 'admin', 'ru')).toBeNull();
  });

  it('keeps source actuality, import alternatives, and admin operations language user-facing', () => {
    const documents = getContextualHelp('/documents', 'methodologist', 'ru');
    expect(documents?.steps[1]).toContain('отображаемую версию');
    expect(documents?.steps[1]).toContain('владельца и даты проверки');
    expect(documents?.steps[0]).not.toContain('с владельцем');

    const staff = getContextualHelp('/staff', 'methodologist', 'ru');
    expect(staff?.steps.join(' ')).toContain('Импортируйте');
    expect(staff?.steps.join(' ')).not.toContain('только вручную');

    const reports = getContextualHelp('/training-log', 'admin', 'ru');
    expect(reports?.important).toContain('не создаёт курсы и назначения');
    expect(reports?.example).not.toContain('передачи вопроса');

    const operations = getContextualHelp('/admin/super/operations', 'superadmin', 'en');
    expect(operations?.purpose).toContain('background jobs');
    expect(operations?.purpose).not.toContain('worker');

    const providers = getContextualHelp('/admin/providers', 'superadmin', 'ru');
    expect(providers?.important).not.toContain('owner approval');
  });

  it('separates competency and rule configuration from procedure evidence', () => {
    const competencies = getContextualHelp('/competencies', 'methodologist', 'ru');
    expect(competencies?.title).toBe('Матрица компетенций');
    expect(competencies?.steps.join(' ')).toContain('должности и курсы');
    expect(competencies?.important).toContain('не заменяет проверку');

    const rules = getContextualHelp('/training-rules', 'methodologist', 'en');
    expect(rules?.id).toBe('training-rules');
    expect(rules?.steps.join(' ')).toContain('preview');
    expect(rules?.important).toContain('changes nothing');

    const procedures = getContextualHelp('/training-procedures', 'methodologist', 'ru');
    expect(procedures?.purpose).toContain('черновика процедуры');
    expect(procedures?.important).toContain('не является ЭЦП');
    expect(procedures?.important).toContain('не заменяет отдельное решение');
  });

  it('falls back to Russian for an unsupported locale', () => {
    expect(getContextualHelp('/documents', 'methodologist', 'de')?.title).toBe('Документы');
  });

  it('keeps retention help read-only for methodologists', () => {
    const help = getContextualHelp('/training-retention', 'methodologist', 'ru');

    expect(help?.purpose).toContain('Просмотр утверждённых сроков');
    expect(help?.steps.join(' ')).toContain('обратитесь к администратору Kamilya');
    expect(help?.important).toContain('не изменяет политики');
    expect(help?.steps.join(' ')).not.toContain('Активируйте');
  });
});
