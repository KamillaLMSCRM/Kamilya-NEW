// Document upload types accepted by the documents API. Keep both file pickers
// and their multipart MIME types in sync (browser/OS MIME mappings can differ).
const DOCUMENT_TYPES = {
  pdf: 'application/pdf',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  xls: 'application/vnd.ms-excel',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
} as const;

export const DOCUMENT_UPLOAD_ACCEPT = Object.keys(DOCUMENT_TYPES).map(extension => `.${extension}`).join(',');

export function documentUploadFile(file: File): File | null {
  const extension = /\.([^.]+)$/.exec(file.name)?.[1].toLowerCase();
  if (!extension || !Object.prototype.hasOwnProperty.call(DOCUMENT_TYPES, extension)) return null;
  const type = DOCUMENT_TYPES[extension as keyof typeof DOCUMENT_TYPES];
  return file.type === type ? file : new File([file], file.name, { type, lastModified: file.lastModified });
}
