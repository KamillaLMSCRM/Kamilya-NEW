import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const pdfMocks = vi.hoisted(() => ({
  getDocument: vi.fn(),
  workerOptions: {} as { workerSrc?: string },
}));

vi.mock('pdfjs-dist', () => ({
  getDocument: pdfMocks.getDocument,
  GlobalWorkerOptions: pdfMocks.workerOptions,
}));

import PdfPreview from '@/components/PdfPreview';

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (error: unknown) => void };

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function page(text: string, order: string[], renderPromise = Promise.resolve()) {
  return {
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
    getTextContent: vi.fn(async () => ({ items: [{ str: text }] })),
    render: vi.fn(() => {
      order.push(`render:${text}`);
      return { promise: renderPromise, cancel: vi.fn() };
    }),
  };
}

function loadingTask(pdfPromise: Promise<unknown>) {
  return { promise: pdfPromise, destroy: vi.fn() };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('devicePixelRatio', 3);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D);
});

describe('PdfPreview', () => {
  it('renders every page sequentially with capped HiDPI canvases and accessible text', async () => {
    const order: string[] = [];
    const first = page('First page', order);
    const second = page('Second page', order);
    pdfMocks.getDocument.mockReturnValue(
      loadingTask(Promise.resolve({ numPages: 2, getPage: vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second) })),
    );

    const { container } = render(
      <PdfPreview blob={new Blob(['first'])} title="Preview" loadingLabel="Loading" errorLabel="Failed" />,
    );

    await waitFor(() => expect(container.querySelectorAll('canvas')).toHaveLength(2));
    expect(order).toEqual(['render:First page', 'render:Second page']);
    expect(screen.getByText('First page')).toBeInTheDocument();
    expect(screen.getByText('Second page')).toBeInTheDocument();
    expect(container.querySelector('canvas')?.width).toBe(1200);
    expect(pdfMocks.getDocument).toHaveBeenCalledWith({
      data: new Uint8Array([102, 105, 114, 115, 116]),
      isEvalSupported: false,
      enableXfa: false,
    });
  });

  it('shows only the supplied generic error when PDF loading fails', async () => {
    pdfMocks.getDocument.mockImplementation(() =>
      loadingTask(Promise.reject(new Error('internal PDF details'))),
    );

    const { container } = render(
      <PdfPreview blob={new Blob(['bad'])} title="Preview" loadingLabel="Loading" errorLabel="Unable to preview" />,
    );

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to preview');
    expect(container).not.toHaveTextContent('internal PDF details');
    expect(container.querySelector('canvas')).toBeNull();
  });

  it('destroys a pending loading task and cancels an active render on unmount', async () => {
    const pdfReady = deferred<unknown>();
    const renderReady = deferred<void>();
    const renderCancel = vi.fn();
    const renderPage = {
      ...page('Pending', []),
      render: vi.fn(() => ({ promise: renderReady.promise, cancel: renderCancel })),
    };
    const task = loadingTask(pdfReady.promise);
    pdfMocks.getDocument.mockReturnValue(task);
    const view = render(
      <PdfPreview blob={new Blob(['pending'])} title="Preview" loadingLabel="Loading" errorLabel="Failed" />,
    );
    pdfReady.resolve({ numPages: 1, getPage: vi.fn().mockResolvedValue(renderPage) });
    await waitFor(() => expect(renderPage.render).toHaveBeenCalled());
    view.unmount();

    expect(renderCancel).toHaveBeenCalledTimes(1);
    expect(task.destroy).toHaveBeenCalledTimes(1);
  });

  it('does not start the next page until the current page render resolves', async () => {
    const renderReady = deferred<void>();
    const order: string[] = [];
    const first = page('First page', order, renderReady.promise);
    const second = page('Second page', order);
    const getPage = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(second);
    pdfMocks.getDocument.mockReturnValue(loadingTask(Promise.resolve({ numPages: 2, getPage })));

    render(<PdfPreview blob={new Blob(['ordered'])} title="Preview" loadingLabel="Loading" errorLabel="Failed" />);
    await waitFor(() => expect(first.render).toHaveBeenCalledTimes(1));
    expect(getPage).toHaveBeenCalledTimes(1);
    expect(second.render).not.toHaveBeenCalled();

    renderReady.resolve();
    await waitFor(() => expect(second.render).toHaveBeenCalledTimes(1));
    expect(getPage).toHaveBeenCalledTimes(2);
  });

  it('ignores stale completion after the PDF blob changes', async () => {
    const firstPdf = deferred<unknown>();
    const firstTask = loadingTask(firstPdf.promise);
    const secondPage = page('Current document', []);
    pdfMocks.getDocument.mockReturnValueOnce(firstTask).mockReturnValueOnce(
      loadingTask(Promise.resolve({ numPages: 1, getPage: vi.fn().mockResolvedValue(secondPage) })),
    );

    const view = render(
      <PdfPreview blob={new Blob(['old'])} title="Preview" loadingLabel="Loading" errorLabel="Failed" />,
    );
    await waitFor(() => expect(pdfMocks.getDocument).toHaveBeenCalledTimes(1));
    view.rerender(<PdfPreview blob={new Blob(['new'])} title="Preview" loadingLabel="Loading" errorLabel="Failed" />);
    firstPdf.resolve({ numPages: 1, getPage: vi.fn().mockResolvedValue(page('Stale document', [])) });

    await waitFor(() => expect(screen.getByText('Current document')).toBeInTheDocument());
    expect(screen.queryByText('Stale document')).toBeNull();
    expect(firstTask.destroy).toHaveBeenCalledTimes(1);
  });
});
