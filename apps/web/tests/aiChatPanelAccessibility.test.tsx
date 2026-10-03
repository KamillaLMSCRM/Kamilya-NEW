import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';

const tMock = (key: string) => ({
  'aiAssistant.dialogLabel': 'Methodologist AI assistant',
  'aiAssistant.title': 'AI assistant',
  'aiAssistant.intro': 'Ask about the course.',
  'aiAssistant.chatPlaceholder': 'Ask AI…',
  'aiGeneration.chat.send': 'Send',
  'common.close': 'Close',
}[key] ?? key);

vi.mock('@/store/authStore', () => ({
  useAuthStore: (selector: (state: { accessToken: string }) => unknown) => selector({ accessToken: 'test-token' }),
}));
vi.mock('@/i18n/useT', () => ({ useT: () => ({ lang: 'en', t: tMock }) }));
vi.mock('@/components/ui/Toast', () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { AIChatPanel } from '@/components/ai/AIChatPanel';

describe('AIChatPanel accessibility', () => {
  beforeEach(() => vi.clearAllMocks());

  it('exposes named dialog controls and closes through the named close button', () => {
    const onClose = vi.fn();
    render(<AIChatPanel open onClose={onClose} courseId="course-1" />);

    expect(screen.getByRole('dialog', { name: 'Methodologist AI assistant' })).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Ask AI…' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('keeps the send button disabled until a message is entered', () => {
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    const input = screen.getByRole('textbox', { name: 'Ask AI…' });
    const send = screen.getByRole('button', { name: 'Send' });
    expect(send).toBeDisabled();
    fireEvent.change(input, { target: { value: '  hello  ' } });
    expect(send).toBeEnabled();
  });

  it('closes on Escape and restores focus to the opener', async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return <><button type="button" onClick={() => setOpen(true)}>Open assistant</button><AIChatPanel open={open} onClose={() => setOpen(false)} courseId="course-1" /></>;
    }
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open assistant' });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Ask AI…' })).toHaveFocus());
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('wraps Tab focus within the panel', async () => {
    render(<AIChatPanel open onClose={vi.fn()} courseId="course-1" />);
    const close = screen.getByRole('button', { name: 'Close' });
    const send = screen.getByRole('button', { name: 'Send' });
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Ask AI…' })).toHaveFocus());
    send.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(close).toHaveFocus();
  });

  it('keeps the original opener across parent rerenders with fresh close callbacks', async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      const [, refresh] = useState(0);
      return <>
        <button type="button" onClick={() => setOpen(true)}>Open assistant</button>
        <AIChatPanel open={open} onClose={() => setOpen(false)} courseId="course-1" />
        {open && <button type="button" onClick={() => refresh((value) => value + 1)}>Refresh parent</button>}
      </>;
    }
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open assistant' });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Ask AI…' })).toHaveFocus());
    const refresh = screen.getByRole('button', { name: 'Refresh parent' });
    refresh.focus();
    fireEvent.click(refresh);
    expect(refresh).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(opener).toHaveFocus());
  });
});
