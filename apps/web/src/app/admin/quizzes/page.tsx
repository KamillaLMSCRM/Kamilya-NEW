'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

// /admin/quizzes was moved to /quizzes on 2026-06-26 so methodologists
// (teacher role) can manage pass_score / attempt_limit / time_limit on
// the quizzes they create. See Sidebar — "Тесты" item.
export default function AdminQuizzesRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/quizzes');
  }, [router]);
  return null;
}