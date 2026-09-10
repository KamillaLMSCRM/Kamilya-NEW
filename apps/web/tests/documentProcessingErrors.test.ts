import { documentProcessingErrorMessage } from '@/lib/documentProcessingErrors';
import { describe, expect, it } from 'vitest';

describe('document processing error message', () => {
  it('gives an actionable message for known document error codes', () => {
    expect(documentProcessingErrorMessage('source_blob_missing')).toBe('Исходный файл недоступен. Загрузите новую версию документа.');
    expect(documentProcessingErrorMessage('ocr_required')).toBe('Для этого документа требуется распознавание текста. Загрузите версию с текстовым слоем.');
  });

  it('never exposes raw provider diagnostics, URLs, or API-key material', () => {
    const raw = 'All embedding providers failed: [qwen-self-hosted] https://internal.example/v1 key=sk-secret-value';
    const message = documentProcessingErrorMessage(null, raw);

    expect(message).toBe('Документ сохранён, но его обработка временно недоступна. Повторите обработку позже.');
    expect(message).not.toContain('qwen');
    expect(message).not.toContain('https://');
    expect(message).not.toContain('sk-secret');
  });

  it.each(['toString', '__proto__', 'constructor'])('does not resolve inherited key %s', (errorCode) => {
    expect(documentProcessingErrorMessage(errorCode)).toBe('Документ сохранён, но его обработка временно недоступна. Повторите обработку позже.');
  });
});
