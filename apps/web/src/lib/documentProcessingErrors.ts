const GENERIC_MESSAGE = 'Документ сохранён, но его обработка временно недоступна. Повторите обработку позже.';

const SAFE_MESSAGES: Record<string, string> = {
  source_blob_missing: 'Исходный файл недоступен. Загрузите новую версию документа.',
  ocr_required: 'Для этого документа требуется распознавание текста. Загрузите версию с текстовым слоем.',
  document_processing: 'Документ ещё обрабатывается. Повторите попытку после завершения индексации.',
  embedding_failed: GENERIC_MESSAGE,
};

export const documentProcessingErrorMessage = (errorCode?: string | null, _rawMessage?: string | null): string =>
  (errorCode && Object.hasOwn(SAFE_MESSAGES, errorCode) && SAFE_MESSAGES[errorCode]) || GENERIC_MESSAGE;
