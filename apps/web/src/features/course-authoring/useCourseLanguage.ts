'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { isCourseLanguage, type CourseLanguage } from './courseLanguages';

type State = { primary: CourseLanguage | null; available: CourseLanguage[]; content: Record<string, string> };

export function useCourseLanguage(courseId: string, identity: string | undefined, fallbackLanguage: string) {
  const [selection, setSelection] = useState<{ scope: string; value: CourseLanguage }>();
  const [result, setResult] = useState<{ scope: string; language: CourseLanguage; data: State }>();
  const scope = identity && `course-language:${identity}:${courseId}`;
  const chosen = selection?.scope === scope ? selection?.value : undefined;
  const stored = typeof window === 'undefined' || !scope ? null : localStorage.getItem(scope);
  const preferred = chosen ?? (isCourseLanguage(stored) ? stored : undefined);
  const fallback = isCourseLanguage(fallbackLanguage) ? fallbackLanguage : 'ru';

  useEffect(() => {
    if (!scope || !courseId) return;
    let active = true;
    const path = `/v1/courses/${courseId}/languages`;
    const requested = preferred ?? fallback;
    void api.get<State>(path, { params: { language: requested } }).then(({ data }) => {
      if (!active || !data.primary) return;
      const language = data.available.includes(requested) ? requested : data.primary;
      setResult({ scope, language, data });
    }).catch(() => { if (active) setResult(undefined); });
    return () => { active = false; };
  }, [courseId, scope, preferred, fallback]);

  const ready = result?.scope === scope ? result : undefined;
  const content = ready?.data.content;
  return {
    language: ready?.language,
    available: ready?.data.available ?? [],
    choose(language: CourseLanguage) {
      if (!scope) return;
      localStorage.setItem(scope, language);
      setSelection({ scope, value: language });
    },
    text<T extends string | null | undefined>(kind: string, id: string, key: string, original: T): string | T {
      return content?.[`${kind}.${id}.${key}`] ?? original;
    },
  };
}
