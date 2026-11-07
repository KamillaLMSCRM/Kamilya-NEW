import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthenticatedSourceImage, isAllowedSourceImageUrl, ReviewSourceImageProvider, sourceImageLine } from '@/components/AuthenticatedSourceImage';
import { ReviewCoursePlayer } from '@/components/course-approval/ReviewCoursePlayer';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', () => ({ api: { get: mocks.get } }));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'en', t: (key: string) => key }) }));
vi.mock('@/store/authStore', () => ({ useAuthStore: (select: (state: { sessionEpoch: number }) => unknown) => select({ sessionEpoch: 1 }) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); mocks.get.mockReset(); });

describe('source image routes', () => {
  const uuid = '3021ee52-3387-46b2-a6c4-a7bd36136ffa';
  const asset = 'asset-' + 'a'.repeat(64);
  const document = `/v1/documents/${uuid}/editorial-review/assets/${asset}?preparation_sha256=${'b'.repeat(64)}`;
  const lesson = `/v1/courses/${uuid}/lessons/${uuid}/source-assets/${asset}`;
  it('accepts only exact same-origin server routes', () => {
    expect(isAllowedSourceImageUrl(document)).toBe(true);
    expect(isAllowedSourceImageUrl(lesson)).toBe(true);
    for (const url of [`https://example.com${lesson}`, `//example.com${lesson}`, `${lesson}?x=1`, `${document}&x=1`, 'data:image/png;base64,a', `${lesson}/../other`]) {
      expect(isAllowedSourceImageUrl(url)).toBe(false);
    }
  });
  it('only treats a whole allowlisted markdown image line as a figure', () => {
    expect(sourceImageLine(`![Caption](${lesson})`)).toEqual({ alt: 'Caption', url: lesson });
    expect(sourceImageLine('![Caption](https://example.com/a.png)')).toBeNull();
    expect(sourceImageLine(`prefix ![Caption](${lesson})`)).toBeNull();
  });
  it('fetches a protected blob and revokes its object URL on unmount', async () => {
    mocks.get.mockResolvedValueOnce({ data: new Blob(['image'], { type: 'image/png' }) });
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:source');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const view = render(<AuthenticatedSourceImage url={lesson} alt="Diagram" />);
    expect(await screen.findByRole('img', { name: 'Diagram' })).toHaveAttribute('src', 'blob:source');
    expect(mocks.get).toHaveBeenCalledWith(lesson, expect.objectContaining({ responseType: 'blob' }));
    view.unmount();
    expect(create).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith('blob:source');
  });
  it.each(['guest', 'account'] as const)('fetches review images through the active attempt using %s authorization', async mode => {
    const attempt = 'b5b93138-cf8e-4e06-a87b-278e21efe8e2';
    const actualLesson = '7916f4bf-5c05-4930-bb30-49b84e171709';
    const snapshot = { schema_version: 1, release_version: 1, course: { id: uuid, title: 'Course' }, modules: [
      { id: uuid, title: 'Module', order_index: 0, lessons: [
        { id: actualLesson, title: 'Lesson', content_type: 'text', content: `![Diagram](${lesson})`, order_index: 0, quizzes: [] },
      ] },
    ] };
    mocks.get.mockResolvedValueOnce({ data: new Blob(['image'], { type: 'image/png' }) });
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:review');
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    render(<ReviewCoursePlayer snapshot={snapshot} attemptId={attempt} token={mode === 'guest' ? 'capability' : undefined} onComplete={() => {}} />);
    await screen.findByRole('img', { name: 'Diagram' });
    const expectedUrl = `/v1/course-review-attempts/${attempt}/lessons/${actualLesson}/source-assets/${asset}`;
    const expectedAuth = mode === 'guest' ? { headers: { Authorization: 'Bearer capability' } } : { reviewerAccountSession: true };
    expect(mocks.get).toHaveBeenCalledWith(expectedUrl, expect.objectContaining(expectedAuth));
    expect(mocks.get).not.toHaveBeenCalledWith(lesson, expect.anything());
    expect(expectedUrl).not.toContain('capability');
  });
  it('removes an old capability image immediately when the review identity changes', async () => {
    mocks.get.mockResolvedValueOnce({ data: new Blob(['image'], { type: 'image/png' }) });
    mocks.get.mockImplementationOnce(() => new Promise(() => {}));
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:review');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const renderImage = (token: string) => <ReviewSourceImageProvider attemptId={uuid} lessonId={uuid} token={token}>
      <AuthenticatedSourceImage url={lesson} alt="Diagram" />
    </ReviewSourceImageProvider>;
    const view = render(renderImage('first'));
    await screen.findByRole('img', { name: 'Diagram' });
    view.rerender(renderImage('second'));
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(revoke).toHaveBeenCalledWith('blob:review');
    expect(await screen.findByRole('status')).toHaveTextContent('Loading image');
  });
  it('never falls back to an ordinary document image inside review context', () => {
    render(<ReviewSourceImageProvider attemptId={uuid} lessonId={uuid} token="capability">
      <AuthenticatedSourceImage url={document} alt="Diagram" />
    </ReviewSourceImageProvider>);
    expect(screen.getByRole('status')).toHaveTextContent('Could not load image');
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
