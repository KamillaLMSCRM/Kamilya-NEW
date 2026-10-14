import { beforeEach, describe, expect, it, vi } from 'vitest';

const get = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ api: { get } }));
import { loadCorrectionSourceFile } from '@/lib/lessonCorrection';

const id = '11111111-1111-4111-8111-111111111111';
const metadata = { id, title: 'Инструкция склада', filename: 'Инструкция.pdf', content_type: 'application/pdf', size: 4 };
const file = () => new Blob(['%PDF'], { type: 'application/pdf' });

describe('correction source file transport', () => {
  beforeEach(() => { get.mockReset(); });

  it('uses only the existing authenticated metadata and byte endpoints with one signal', async () => {
    get.mockResolvedValueOnce({ data: { ...metadata, signed_url: 'https://untrusted.example/file' } }).mockResolvedValueOnce({ data: file() });
    const controller = new AbortController();
    const result = await loadCorrectionSourceFile(id, controller.signal);
    expect(get.mock.calls).toEqual([
      [`/v1/documents/${id}`, { signal: controller.signal }],
      [`/v1/documents/${id}/download`, { signal: controller.signal, responseType: 'blob' }],
    ]);
    expect(result).toEqual({ blob: expect.any(Blob), filename: 'Инструкция.pdf', title: metadata.title });
  });

  it('rejects a non-UUID before any request', async () => {
    await expect(loadCorrectionSourceFile('../other')).rejects.toThrow(); expect(get).not.toHaveBeenCalled();
  });

  it.each([
    { id: '22222222-2222-4222-8222-222222222222' }, { filename: '' }, { title: null },
    { content_type: null }, { size: 0 }, { size: 1.5 }, { filename: 'x'.repeat(1025) },
  ])('refuses malformed or foreign metadata %j before byte retrieval', async (delta) => {
    get.mockResolvedValueOnce({ data: { ...metadata, ...delta } });
    await expect(loadCorrectionSourceFile(id)).rejects.toThrow('Invalid source file'); expect(get).toHaveBeenCalledTimes(1);
  });

  it('sanitizes path, control and directional filename characters without trusting disposition', async () => {
    get.mockResolvedValueOnce({ data: { ...metadata, filename: '../folder/\\\u202EИнструкция\u0000?.pdf' } }).mockResolvedValueOnce({ data: file() });
    expect((await loadCorrectionSourceFile(id)).filename).toBe('Инструкция_.pdf');
  });

  it.each([null, 'error', new Blob([]), new Blob(['%PDF'], { type: 'text/html' }), new Blob(['short'], { type: 'application/pdf' })])('rejects invalid, mismatched or error bodies', async (body) => {
    get.mockResolvedValueOnce({ data: metadata }).mockResolvedValueOnce({ data: body });
    await expect(loadCorrectionSourceFile(id)).rejects.toThrow('Invalid source file');
  });

  it.each([401, 403, 404, 503])('does not mask HTTP %s or retry', async (status) => {
    const error = { response: { status } }; get.mockRejectedValue(error);
    await expect(loadCorrectionSourceFile(id)).rejects.toBe(error); expect(get).toHaveBeenCalledTimes(1);
  });

  it('does not retrieve bytes if metadata completes after cancellation', async () => {
    const controller = new AbortController();
    get.mockImplementationOnce(async () => { controller.abort(); return { data: metadata }; });
    await expect(loadCorrectionSourceFile(id, controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('rejects already aborted work without I/O', async () => {
    const controller = new AbortController(); controller.abort();
    await expect(loadCorrectionSourceFile(id, controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(get).not.toHaveBeenCalled();
  });
});
