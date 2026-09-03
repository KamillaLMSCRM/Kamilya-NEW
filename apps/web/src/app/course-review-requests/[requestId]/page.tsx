'use client';

import { useParams } from 'next/navigation';
import { ReviewRequestScreen } from '@/components/course-approval/ReviewRequestScreen';

export default function CourseReviewRequestPage() {
  const params = useParams<{ requestId: string }>();
  return <ReviewRequestScreen requestId={params.requestId} />;
}
