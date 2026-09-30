export interface LearnerAssignment {
  course_id: string;
  enrollment_id?: string;
  title: string;
  enrollment_status: string;
  enrolled_at: string;
  assignment_due_at?: string | null;
  assignment_source?: string | null;
  resume_href?: string | null;
  progress_percent?: number;
  can_resume?: boolean;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function selectNextAssignment<T extends LearnerAssignment>(courses: T[]): T | null {
  return courses
    .filter((course) => course.enrollment_status !== 'completed' && course.can_resume !== false)
    .slice()
    .sort((left, right) => {
      const leftDue = left.assignment_due_at ? Date.parse(left.assignment_due_at) : Number.NaN;
      const rightDue = right.assignment_due_at ? Date.parse(right.assignment_due_at) : Number.NaN;
      const leftHasDue = Number.isFinite(leftDue);
      const rightHasDue = Number.isFinite(rightDue);
      if (leftHasDue !== rightHasDue) return leftHasDue ? -1 : 1;
      if (leftHasDue && rightHasDue && leftDue !== rightDue) return leftDue - rightDue;
      const enrolledOrder = Date.parse(left.enrolled_at) - Date.parse(right.enrolled_at);
      if (Number.isFinite(enrolledOrder) && enrolledOrder !== 0) return enrolledOrder;
      const courseOrder = left.course_id.localeCompare(right.course_id);
      if (courseOrder !== 0) return courseOrder;
      return (left.enrollment_id ?? '').localeCompare(right.enrollment_id ?? '');
    })[0] ?? null;
}

export function safeResumeHref(course: LearnerAssignment): string {
  if (!UUID_RE.test(course.course_id)) return '/courses';
  const base = `/courses/${course.course_id}`;
  const href = course.resume_href;
  if (!href) return base;
  const exactBase = href === base;
  const lessonMatch = href.match(/^\/courses\/([^/?#]+)\?lessonId=([^/?#]+)$/);
  if (exactBase) return base;
  if (lessonMatch?.[1] === course.course_id && lessonMatch[2] && UUID_RE.test(lessonMatch[2])) return href;
  return base;
}

const sourceLabels: Record<'ru' | 'kk' | 'en', Record<string, string>> = {
  ru: {
    manual: 'Назначено вручную', cohort: 'Назначено группе', position: 'По должности',
    department: 'По подразделению', organization: 'По организации', learning_path: 'По учебному пути', recurring: 'Повторное назначение',
  },
  kk: {
    manual: 'Қолмен тағайындалды', cohort: 'Топқа тағайындалды', position: 'Лауазым бойынша',
    department: 'Бөлім бойынша', organization: 'Ұйым бойынша', learning_path: 'Оқу жолы бойынша', recurring: 'Қайталама тағайындау',
  },
  en: {
    manual: 'Assigned manually', cohort: 'Assigned to a group', position: 'By position',
    department: 'By department', organization: 'By organization', learning_path: 'By learning path', recurring: 'Recurring assignment',
  },
};

export function assignmentSourceLabel(source: string | null | undefined, lang: string): string | null {
  if (!source) return null;
  const locale = lang === 'kk' || lang === 'en' ? lang : 'ru';
  return sourceLabels[locale][source] ?? source;
}

export function formatAssignmentDueAt(dueAt: string | null | undefined, lang: string): string | null {
  if (!dueAt || !Number.isFinite(Date.parse(dueAt))) return null;
  try {
    return new Intl.DateTimeFormat(lang, { dateStyle: 'medium' }).format(new Date(dueAt));
  } catch {
    return null;
  }
}

export const studentDailyLearningCopy = {
  ru: {
    due: 'Срок', source: 'Основание назначения', retry: 'Повторить загрузку',
    loadError: 'Не удалось загрузить обучение. Попробуйте ещё раз.',
    remainingSteps: 'Уроки пройдены. Завершите оставшиеся шаги в курсе.', overdue: 'Срок прошёл',
    assignmentAccessRequired: 'Продолжение этого назначения пока недоступно. Обратитесь к методисту, чтобы согласовать способ продолжения.',
  },
  kk: {
    due: 'Мерзімі', source: 'Тағайындау себебі', retry: 'Қайта жүктеу',
    loadError: 'Оқытуды жүктеу мүмкін болмады. Қайталап көріңіз.',
    remainingSteps: 'Сабақтар аяқталды. Курстағы қалған қадамдарды аяқтаңыз.', overdue: 'Мерзімі өтті',
    assignmentAccessRequired: 'Бұл тағайындау бойынша оқуды жалғастыру әзірге қолжетімсіз. Жалғастыру жолын келісу үшін әдіскерге хабарласыңыз.',
  },
  en: {
    due: 'Due', source: 'Assignment reason', retry: 'Retry loading',
    loadError: 'Could not load your learning. Please try again.',
    remainingSteps: 'Lessons are complete. Finish the remaining steps in the course.', overdue: 'Past due',
    assignmentAccessRequired: 'Continuing this assignment is not available yet. Ask your methodologist how to continue.',
  },
} as const;
