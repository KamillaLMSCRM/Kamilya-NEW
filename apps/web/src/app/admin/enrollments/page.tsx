import { redirect } from 'next/navigation';

// Legacy route: course/learner assignments are learning-content work,
// not tenant administration. Keep old links working while the UI points
// to /assignments.
export default function AdminEnrollmentsRedirect() {
  redirect('/assignments');
}
