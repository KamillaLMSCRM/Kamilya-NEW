/** Reject HTML/error blobs before displaying either admin template preview. */
export async function isPdfPreview(blob: Blob): Promise<boolean> {
  if (blob.type.split(';')[0].trim().toLowerCase() !== 'application/pdf' || blob.size < 5) {
    return false;
  }
  // Read only the PDF magic bytes, not the full document. FileReader also works
  // in browsers/test runtimes without Blob.text(). This is not a PDF malware scan.
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result === '%PDF-');
    reader.onerror = () => resolve(false);
    reader.onabort = () => resolve(false);
    reader.readAsText(blob.slice(0, 5));
  });
}
