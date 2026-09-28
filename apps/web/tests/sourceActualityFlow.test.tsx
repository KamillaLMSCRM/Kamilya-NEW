import { describe, expect, it } from 'vitest';

const fs = await import('node:fs');
const path = await import('node:path');

const featurePath = path.resolve(process.cwd(), 'src/features/source-actuality/SourceActualityPanel.tsx');
const documentsPage = fs.readFileSync(path.resolve(process.cwd(), 'src/app/documents/page.tsx'), 'utf8');

describe('source actuality methodologist UI contract', () => {
  it('joins actuality onto the canonical document catalogue by source family', () => {
    expect(documentsPage).toContain('<SourceActualityPanel');
    expect(documentsPage).toContain('catalogDocuments={documents}');
    expect(fs.existsSync(featurePath)).toBe(true);
    const source = fs.readFileSync(featurePath, 'utf8');
    expect(source).toContain('source_family_id');
    expect(source).toContain('latest_document_id');
  });

  it('uses the source actuality API contracts and keeps decisions explicit', () => {
    const source = fs.readFileSync(featurePath, 'utf8');
    expect(source).toContain('/v1/admin/source-actuality');
    expect(source).toContain('/policy');
    expect(source).toContain('owner_id: owner');
    expect(source).toContain('reviewed_at: toAwareIso(reviewedAt)');
    expect(source).toContain('next_review_at: toAwareIso(nextReviewAt)');
    expect(source).not.toContain('localDateTime(family.reviewed_at) || new Date().toISOString().slice(0, 16)');
    expect(source).toContain('/analyze');
    expect(source).toContain('/reviews/');
    expect(source).toContain("window.setInterval");
    expect(source).toContain('assessment_questions_requiring_review');
    expect(source).toContain('changed_fact_count');
    expect(source).toContain('changed_facts');
    expect(source).toContain('active_enrollments');
    expect(source).toContain('completed_enrollments');
    expect(source).toContain('facts.slice(0, 10)');
    expect(source).toContain('update_and_retrain');
    expect(source).toContain('retraining_due_at');
    expect(source).toContain('reason: reason.trim()');
    expect(source).toContain('documents.sourceActuality.noAutoPublish');
    expect(source).toContain('documents.sourceActuality.questionScope');
    expect(source).toContain('role="dialog"');
    expect(source).not.toContain('{family.source_family_id}</');
    expect(source).not.toContain('{active.pending_review_id}</');
  });

  it('keeps all visible source actuality copy localized in RU, KK and EN', () => {
    for (const locale of ['ru', 'kk', 'en']) {
      const translations = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), `src/i18n/locales/${locale}.json`), 'utf8'));
      expect(translations.documents.sourceActuality.title).toBeTruthy();
      expect(translations.documents.sourceActuality.overdue).toBeTruthy();
      expect(translations.documents.sourceActuality.noAutoPublish).toBeTruthy();
    }
  });
});
