export const contentLanguages = { ru: 'Русский', kk: 'Қазақша', en: 'English' } as const;
export type CourseLanguage = keyof typeof contentLanguages;

export function isCourseLanguage(value: string | null | undefined): value is CourseLanguage {
  return value === 'ru' || value === 'kk' || value === 'en';
}
