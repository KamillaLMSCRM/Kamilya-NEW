// Backward-compat redirect: /admin/users → /admin/team (ADR-0011).
//
// The team-management surface was renamed and restricted to non-student
// roles. Existing bookmarks pointing to /admin/users should still work.

import { redirect } from 'next/navigation';

export default function AdminUsersRedirect() {
  redirect('/admin/team');
}