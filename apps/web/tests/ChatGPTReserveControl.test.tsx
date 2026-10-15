import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/i18n/useT', () => ({
  useT: () => ({ t: (key: string) => ({
    'providers.chatgptReserve.button': 'ChatGPT reserve',
    'providers.chatgptReserve.title': 'ChatGPT reserve',
    'providers.chatgptReserve.description': 'Manual Codex CLI reserve',
    'providers.chatgptReserve.status': 'Status',
    'providers.chatgptReserve.enabled': 'Enabled',
    'providers.chatgptReserve.disabled': 'Disabled',
    'providers.chatgptReserve.configured': 'Codex CLI connection configured. Readiness checked separately.',
    'providers.chatgptReserve.notConfigured': 'Not configured',
    'providers.chatgptReserve.readiness': 'Readiness',
    'providers.chatgptReserve.readinessNotChecked': 'Not checked',
    'providers.chatgptReserve.checkReadiness': 'Check readiness',
    'providers.chatgptReserve.enable': 'Enable reserve',
    'providers.chatgptReserve.disable': 'Disable reserve',
    'providers.chatgptReserve.confirmEnable': 'Confirm enable',
    'providers.chatgptReserve.docs': 'Codex CLI docs',
    'providers.chatgptReserve.docsWarning': 'CLI availability does not prove model answers or hosted applicability',
    'providers.chatgptReserve.reasonUnknown': 'Unknown',
    'providers.chatgptReserve.reasons.ready': 'Ready',
    'providers.chatgptReserve.reasons.authorization_required': 'Authorization required',
    'providers.chatgptReserve.loadError': 'Load failed',
    'providers.routingRetry': 'Retry',
  }[key] ?? key), }),
}));

vi.mock('@/components/ui', () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
  Badge: ({ children }: any) => <span>{children}</span>,
  Modal: ({ open, children, onClose, dismissable }: any) => open ? <div role="dialog"><button type="button" aria-label="Close" disabled={!dismissable} onClick={onClose}>Close</button>{children}</div> : null,
}));

import { ChatGPTReserveControl } from '@/components/admin/ChatGPTReserveControl';

const route = {
  id: 'chatgpt_reserve', provider: 'chatgpt', display_name: 'ChatGPT reserve', model: 'gpt',
  is_enabled: false, position: null, is_required: false, is_configured: true,
};
const baseProps = () => ({
  route, readiness: null, loading: false, loadError: false, checking: false, saving: false,
  open: true, onOpen: vi.fn(), onClose: vi.fn(), onCheck: vi.fn(), onRetry: vi.fn(),
  onEnable: vi.fn(), onDisable: vi.fn(),
});

describe('ChatGPTReserveControl', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not probe or write while disabled before explicit readiness check', () => {
    const props = baseProps();
    render(<ChatGPTReserveControl {...props} />);
    expect(props.onCheck).not.toHaveBeenCalled();
    expect(props.onEnable).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Enable reserve' })).toBeDisabled();
  });

  it('performs readiness only after explicit check', () => {
    const props = baseProps();
    render(<ChatGPTReserveControl {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Check readiness' }));
    expect(props.onCheck).toHaveBeenCalledTimes(1);
  });

  it('does not enable when explicit confirmation is cancelled', () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    const props = { ...baseProps(), readiness: { ready: true, reason: 'ready' as const, checked_at: 'now' } };
    render(<ChatGPTReserveControl {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Enable reserve' }));
    expect(props.onEnable).not.toHaveBeenCalled();
  });

  it('enables only after readiness and confirmation', () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    const props = { ...baseProps(), readiness: { ready: true, reason: 'ready' as const, checked_at: 'now' } };
    render(<ChatGPTReserveControl {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Enable reserve' }));
    expect(props.onEnable).toHaveBeenCalledTimes(1);
  });

  it('disables without a readiness prerequisite', () => {
    const props = { ...baseProps(), route: { ...route, is_enabled: true } };
    render(<ChatGPTReserveControl {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Disable reserve' }));
    expect(props.onDisable).toHaveBeenCalledTimes(1);
    expect(props.onCheck).not.toHaveBeenCalled();
    expect(screen.getByText('Enabled')).toBeInTheDocument();
    expect(screen.getByText('Codex CLI connection configured. Readiness checked separately.')).toBeInTheDocument();
    expect(screen.queryByText(/reserve disabled/)).not.toBeInTheDocument();
  });

  it('shows a retry state instead of reporting disabled after load failure', () => {
    const props = { ...baseProps(), loadError: true };
    render(<ChatGPTReserveControl {...props} />);
    expect(screen.getByText('Load failed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Enable reserve' })).not.toBeInTheDocument();
  });

  it('sanitizes an unknown readiness reason instead of rendering it', () => {
    const props = { ...baseProps(), readiness: { ready: false, reason: 'unexpected_internal_detail' as any, checked_at: 'now' } };
    render(<ChatGPTReserveControl {...props} />);
    expect(screen.getByRole('status')).toHaveTextContent('Readiness: Unknown');
    expect(screen.getByRole('status')).not.toHaveTextContent('unexpected_internal_detail');
  });

  it('keeps controls and modal close disabled while checking', () => {
    const props = { ...baseProps(), checking: true };
    render(<ChatGPTReserveControl {...props} />);
    expect(screen.getByRole('button', { name: '…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(props.onClose).not.toHaveBeenCalled();
  });

  it('disables all mutating/readiness controls while saving', () => {
    const props = { ...baseProps(), saving: true, readiness: { ready: true, reason: 'ready' as const, checked_at: 'now' } };
    render(<ChatGPTReserveControl {...props} />);
    expect(screen.getByRole('button', { name: 'Check readiness' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
  });

  it('does not close while loading', () => {
    const props = { ...baseProps(), loading: true };
    render(<ChatGPTReserveControl {...props} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(props.onClose).not.toHaveBeenCalled();
  });
});
