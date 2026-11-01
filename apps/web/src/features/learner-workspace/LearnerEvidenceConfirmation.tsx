'use client';

import { useAuthStore } from '@/store/authStore';
import { EvidenceConfirmationPanel } from '@/features/training-evidence/EvidenceConfirmationPanel';

interface Props {
  eventId: string;
  activityTitle: string;
  activityKind: 'course' | 'quiz';
  continueHref?: string;
  continueLabel?: string;
  resultHref?: string;
  resultLabel?: string;
}

/** Active-role boundary only. The shared panel owns the one scoped read and OTP. */
export function LearnerEvidenceConfirmation(props: Props) {
  const user = useAuthStore((state) => state.user);
  const token = useAuthStore((state) => state.accessToken);
  if (user?.role !== 'student' || !token) return null;
  return <EvidenceConfirmationPanel {...props} />;
}
