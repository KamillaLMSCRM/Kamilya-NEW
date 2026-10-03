import { describe, expect, it } from 'vitest';
import { isPdfPreview } from '@/lib/pdfPreview';

describe('admin PDF preview validation', () => {
  it('accepts a PDF only when both MIME type and signature match', async () => {
    await expect(isPdfPreview(new Blob(['%PDF-1.7\npreview'], { type: 'application/pdf' }))).resolves.toBe(true);
    await expect(isPdfPreview(new Blob(['%PDF-1.7'], { type: 'application/pdf; charset=binary' }))).resolves.toBe(true);
  });

  it.each([
    ['text/html', '<script>alert(1)</script>'],
    ['application/pdf', '<html>error</html>'],
    ['text/html', '%PDF-1.7'],
    ['application/pdf', ''],
    ['application/json', '{"detail":"error"}'],
  ])('rejects %s with invalid or non-PDF content', async (type, body) => {
    await expect(isPdfPreview(new Blob([body], { type }))).resolves.toBe(false);
  });
});
