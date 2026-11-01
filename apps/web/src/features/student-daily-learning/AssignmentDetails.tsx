'use client';

import { useLanguageStore } from '@/store/languageStore';
import { assignmentSourceLabel, formatAssignmentDueAt, studentDailyLearningCopy, type LearnerAssignment } from './nextAssignment';

export function AssignmentDetails({ course }: { course: LearnerAssignment }) {
  const lang = useLanguageStore((state) => state.lang);
  const copy = studentDailyLearningCopy[lang] ?? studentDailyLearningCopy.ru;
  const due = formatAssignmentDueAt(course.assignment_due_at, lang);
  const source = assignmentSourceLabel(course.assignment_source, lang);
  return (
    <div className="my-3 space-y-1 text-xs text-muted-foreground">
      {due && <p>{copy.due}: <time dateTime={course.assignment_due_at!}>{due}</time>{course.enrollment_status !== 'completed' && Date.parse(course.assignment_due_at!) < Date.now() && <span className="ml-2 font-medium text-destructive">{copy.overdue}</span>}</p>}
      {source && <p>{copy.source}: {source}</p>}
      {course.progress_percent !== undefined && course.progress_percent >= 100 && course.enrollment_status !== 'completed' && <p className="font-medium text-primary">{copy.remainingSteps}</p>}
    </div>
  );
}
