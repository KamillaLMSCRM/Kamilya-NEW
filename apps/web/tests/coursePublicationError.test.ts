import { describe, expect, it } from 'vitest';
import { coursePublicationError } from '@/lib/coursePublicationError';
import ru from '@/i18n/locales/ru.json';
import kk from '@/i18n/locales/kk.json';
import en from '@/i18n/locales/en.json';

describe('publication approval failure messages', () => {
  it.each([ru, kk, en])('renders a localized instruction from the production conflict envelope', (locale) => {
    const payload = { error: 'conflict', message: "{'code': 'approval_required'}", details: { code: 'approval_required' } };
    const result = coursePublicationError(payload, key => locale.courseApproval[key.split('.')[1] as keyof typeof locale.courseApproval]);
    expect(result).toBe(locale.courseApproval.publishRequiresApproval);
    expect(result).not.toContain('approval_required');
  });

  it.each(['approval_pending', 'approval_changes_requested', 'approval_superseded', 'approval_revision_mismatch'])('handles %s in a FastAPI detail envelope', code => {
    expect(coursePublicationError({ detail: { code } }, key => key)).toMatch(/^courseApproval\.publish/);
  });

  it.each([null, {}, { details: [] }, { details: { code: 'other' } }, { details: { code: 'constructor' } }])('preserves caller fallback for unrelated errors', payload => {
    expect(coursePublicationError(payload, key => key)).toBeUndefined();
  });
});
