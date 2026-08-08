export const DEMO_ADMIN_COPY = {
  description: 'Настройки организации, системные пользователи, киоски и интеграции',
  redirect: '/admin',
} as const;

// The backend deliberately rejects privileged public demo login in production.
// Keep the public selector aligned with that security boundary.
export const PUBLIC_DEMO_ROLE_IDS = ['methodologist', 'student'] as const;
