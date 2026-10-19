import { describe, expect, it } from 'vitest';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

describe('manual staff required-field guidance', () => {
  it('requires identity and position, not the optional department', () => {
    expect(ru.authenticatedUi.adminStaff.manual.required).toBe('Заполните табельный номер, имя, фамилию и должность');
    expect(kk.authenticatedUi.adminStaff.manual.required).toBe('Табель нөмірін, атын, тегін және лауазымын толтырыңыз');
    expect(en.authenticatedUi.adminStaff.manual.required).toBe('Fill in the personnel number, first name, last name, and position');
  });
});
