import { redirect } from 'next/navigation';

export default function LegacyQuizAssignPage() {
  redirect('/quizzes?section=assignments');
}
