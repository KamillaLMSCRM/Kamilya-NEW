'use client';

import { useParams, useRouter } from 'next/navigation';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';
import { PublicWorkspace } from '@/features/workspace-design';
import { LanguageSwitcher } from '@/components/LanguageSwitcher';

export default function ScopedReviewRequestPage() {
  const params = useParams<{ requestId: string }>();
  const router = useRouter();
  const token = typeof window !== 'undefined' ? sessionStorage.getItem('course_review_token') || undefined : undefined;
  const exit = () => { sessionStorage.removeItem('course_review_token'); router.replace('/login'); };
  return <PublicWorkspace id="review-access-detail" actions={<LanguageSwitcher />}><ReviewRequestScreen requestId={params.requestId} token={token} requireCapability onExit={exit} onCompleted={() => { sessionStorage.removeItem('course_review_token'); }} /></PublicWorkspace>;
}
