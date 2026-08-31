import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TenantDeleteModal } from '@/components/admin/TenantDeleteModal';

describe('TenantDeleteModal', () => {
  it('exposes a selectable slug, copy action, and blocks deletion until it matches', () => {
    const onCopySlug = vi.fn();
    const onConfirm = vi.fn();
    const props = {
      tenant: { name: 'Demo tenant', slug: 'long-demo-tenant-slug' },
      confirmation: '',
      deleting: false,
      onConfirmationChange: vi.fn(),
      onCopySlug,
      onCancel: vi.fn(),
      onConfirm,
    };
    const { rerender } = render(<TenantDeleteModal {...props} />);

    expect(screen.getByLabelText('Slug тенанта')).toHaveAttribute('readonly');
    expect(screen.getByDisplayValue('long-demo-tenant-slug')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Копировать' }));
    expect(onCopySlug).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Удалить навсегда' })).toBeDisabled();

    rerender(<TenantDeleteModal {...props} confirmation="long-demo-tenant-slug" />);
    fireEvent.click(screen.getByRole('button', { name: 'Удалить навсегда' }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
