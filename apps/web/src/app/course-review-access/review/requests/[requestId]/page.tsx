'use client';

import { useParams, useRouter } from 'next/navigation';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';

export default function ScopedReviewRequestPage() {
  const params = useParams<{ requestId: string }>();
  const router = useRouter();
  const token = typeof window !== 'undefined' ? sessionStorage.getItem('course_review_token') || undefined : undefined;
  return <ReviewRequestScreen requestId={params.requestId} token={token} onCompleted={() => { sessionStorage.removeItem('course_review_token'); router.replace('/course-review-access/review'); }} />;
}
