import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import ru from '@/i18n/locales/ru.json';
import en from '@/i18n/locales/en.json';
import kk from '@/i18n/locales/kk.json';
import { interpolate } from '@/i18n/useT';

const shareKeySet = [
  'title',
  'description',
  'selectedRecords',
  'format',
  'formats',
  'expiresAt',
  'maxDownloads',
  'maxDownloadsHint',
  'cancel',
  'createLink',
  'ready',
  'details',
  'linkAriaLabel',
  'revoked',
  'close',
  'copy',
  'copied',
  'revoke',
  'errors',
  'toasts',
] as const;

describe('restricted evidence package sharing UI', () => {
  it.each([
    ['ru', ru.trainingLog.evidence.share],
    ['en', en.trainingLog.evidence.share],
    ['kk', kk.trainingLog.evidence.share],
  ])('has a complete localized contract for %s', (_lang, share) => {
    for (const key of shareKeySet) {
      expect(share).toHaveProperty(key);
    }
    expect(share.description).toMatch(/signature|подпись|қолтаңба/i);
    expect(share.description).toMatch(/not|не|емес/i);
  });

  it('describes the selected count and the download limit without legal overclaiming', () => {
    expect(interpolate(ru.trainingLog.evidence.share.selectedRecords, { count: 2 })).toContain('2');
    expect(ru.trainingLog.evidence.share.description).toContain('не является электронной подписью');
    expect(en.trainingLog.evidence.share.description).toContain('not an electronic signature');
    expect(kk.trainingLog.evidence.share.description).toContain('электрондық цифрлық қолтаңба');
  });

  it('keeps the share surface free of hardcoded Russian UI copy', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/features/training-evidence/EvidenceShareDialog.tsx'),
      'utf8',
    );
    expect(source).not.toMatch(/[\u0400-\u04FF]/);
    expect(source).not.toContain("toLocaleString('ru-RU')");
  });

  it('uses the localized training-log action label', () => {
    const source = fs.readFileSync(
      path.join(process.cwd(), 'src/app/admin/training-log/page.tsx'),
      'utf8',
    );
    expect(source).toContain("t('trainingLog.evidence.shareButton')");
  });
});
