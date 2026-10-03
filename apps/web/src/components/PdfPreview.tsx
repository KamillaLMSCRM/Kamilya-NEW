'use client';

import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from 'pdfjs-dist';

export interface PdfPreviewProps {
  blob: Blob;
  title: string;
  loadingLabel: string;
  errorLabel: string;
}

const srOnlyClass =
  'absolute h-px w-px overflow-hidden whitespace-nowrap border-0 p-0 [clip:rect(0,0,0,0)]';

export default function PdfPreview({ blob, title, loadingLabel, errorLabel }: PdfPreviewProps) {
  const previewRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    let active = true;
    let loadingTask: PDFDocumentLoadingTask | undefined;
    let reader: FileReader | undefined;
    const renderTasks = new Set<RenderTask>();
    const preview = previewRef.current;
    setStatus('loading');
    preview?.replaceChildren();

    const load = async () => {
      const pdfjs = await import('pdfjs-dist');
      if (!active) return;

      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'pdfjs-dist/build/pdf.worker.min.mjs',
        import.meta.url,
      ).toString();
      const buffer = await new Promise<ArrayBuffer>((resolve, reject) => {
        reader = new FileReader();
        reader.onload = () => resolve(reader?.result as ArrayBuffer);
        reader.onerror = () => reject(reader?.error ?? new Error('PDF data could not be read'));
        reader.onabort = () => reject(new Error('PDF data reading was aborted'));
        reader.readAsArrayBuffer(blob);
      });
      if (!active) return;
      loadingTask = pdfjs.getDocument({
        data: new Uint8Array(buffer),
        isEvalSupported: false,
        enableXfa: false,
      });
      const pdf: PDFDocumentProxy = await loadingTask.promise;

      if (!active || !preview) return;
      for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        if (!active) return;
        const page = await pdf.getPage(pageNumber);
        if (!active) return;

        const baseViewport = page.getViewport({ scale: 1 });
        const containerWidth = preview.clientWidth || baseViewport.width;
        const scale = Math.max(0.1, containerWidth / baseViewport.width);
        const viewport = page.getViewport({ scale });
        const devicePixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        const wrapper = document.createElement('section');
        wrapper.setAttribute('aria-label', `${title} — page ${pageNumber}`);
        wrapper.className = 'relative w-full overflow-hidden';

        const canvas = document.createElement('canvas');
        canvas.setAttribute('role', 'img');
        canvas.setAttribute('aria-label', `${title} — page ${pageNumber}`);
        canvas.style.display = 'block';
        canvas.style.width = '100%';
        canvas.style.maxWidth = '100%';
        canvas.width = Math.ceil(viewport.width * devicePixelRatio);
        canvas.height = Math.ceil(viewport.height * devicePixelRatio);
        wrapper.append(canvas);

        const textContent = await page.getTextContent();
        if (!active) return;
        const accessibleText = document.createElement('div');
        accessibleText.className = srOnlyClass;
        accessibleText.setAttribute('aria-label', `${title} — page ${pageNumber} text`);
        accessibleText.textContent = textContent.items
          .map((item) => ('str' in item ? item.str : ''))
          .join(' ')
          .trim();
        wrapper.append(accessibleText);
        preview.append(wrapper);

        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas rendering is unavailable');
        const transform: [number, number, number, number, number, number] | undefined =
          devicePixelRatio === 1 ? undefined : [devicePixelRatio, 0, 0, devicePixelRatio, 0, 0];
        const renderTask = page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform,
        });
        renderTasks.add(renderTask);
        try {
          await renderTask.promise;
        } finally {
          renderTasks.delete(renderTask);
        }
      }
      if (active) setStatus('ready');
    };

    void load().catch(() => {
      if (!active) return;
      preview?.replaceChildren();
      setStatus('error');
    });

    return () => {
      active = false;
      renderTasks.forEach((renderTask) => renderTask.cancel());
      renderTasks.clear();
      preview?.replaceChildren();
      if (reader?.readyState === FileReader.LOADING) reader.abort();
      void Promise.resolve(loadingTask?.destroy()).catch(() => undefined);
    };
  }, [blob, title]);

  return (
    <div className="relative w-full overflow-x-hidden" aria-label={title} aria-busy={status === 'loading'}>
      {status === 'loading' ? <p role="status">{loadingLabel}</p> : null}
      {status === 'error' ? <p role="alert">{errorLabel}</p> : null}
      <div ref={previewRef} className="w-full" />
    </div>
  );
}
