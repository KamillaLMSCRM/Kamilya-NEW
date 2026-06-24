'use client';

import { ErrorPage } from '@/components/ui/ErrorPage';

export default function NotFound() {
  return <ErrorPage statusCode={404} title="Страница не найдена" message="Запрашиваемая страница не существует" />;
}
