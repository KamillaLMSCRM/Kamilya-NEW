type QuizLike = { id: string };

type GroupedQuizzes<TQuiz extends QuizLike> = {
  courses: Array<{
    modules: Array<{
      lessons: Array<{ quiz: TQuiz | null }>;
    }>;
  }>;
  orphans: Array<{ quiz: TQuiz }>;
};

export function firstQuizForAssignments<TQuiz extends QuizLike>(
  grouped: GroupedQuizzes<TQuiz>,
): TQuiz | null {
  for (const course of grouped.courses) {
    for (const courseModule of course.modules) {
      for (const lesson of courseModule.lessons) {
        if (lesson.quiz) return lesson.quiz;
      }
    }
  }
  return grouped.orphans[0]?.quiz ?? null;
}
