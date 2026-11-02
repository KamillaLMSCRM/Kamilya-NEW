import { fireEvent, render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CoursePreviewTree } from '../src/app/ai/generate/components/CoursePreview';
import { useLanguageStore } from '../src/store/languageStore';
afterEach(() => { cleanup(); useLanguageStore.setState({ lang: 'ru' }); });
describe('source review warning', () => {
  it.each([
    ['en', 'Source accuracy and coverage require review before approving the course.'],
    ['ru', 'Проверьте точность и полноту по источникам перед одобрением курса.'],
    ['kk', 'Курсты мақұлдамас бұрын дереккөздер бойынша дәлдігі мен толықтығын тексеріңіз.'],
  ] as const)('shows neutral review wording for an untouched lesson in %s', (lang, warning) => {
    useLanguageStore.setState({ lang });
    const noop = vi.fn();
    render(<CoursePreviewTree modules={[{ id: 'm', title: 'Module', lessons: [
      { id: 'l', title: 'Lesson', content_preview: 'Synthetic', source_references: [], source_validation_status: 'needs_review' },
      { id: 'v', title: 'Verified lesson', content_preview: 'Synthetic', source_references: [], source_validation_status: 'verified' },
    ] }]} busyTargetId={null} editingLessonId={null} editForm={{ title: '', content: '' }} editSaving={false}
      onRegenerateModule={noop} onRegenerateLesson={noop} onFocusChat={noop} onEditLesson={noop}
      onCancelEdit={noop} onSaveEdit={noop} onEditFormChange={noop} />);
    fireEvent.click(screen.getByRole('button', { name: /Module/ }));
    expect(screen.getAllByText(warning)).toHaveLength(1);
  });
});
