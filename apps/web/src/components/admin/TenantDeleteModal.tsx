'use client';

import { Button, Input, Modal } from '@/components/ui';

interface TenantDeleteTarget {
  name: string;
  slug: string;
}

interface TenantDeleteModalProps {
  tenant: TenantDeleteTarget | null;
  confirmation: string;
  deleting: boolean;
  onConfirmationChange: (value: string) => void;
  onCopySlug: () => void;
  onCancel: () => void;
  onConfirm: () => void;
}

export function TenantDeleteModal({
  tenant,
  confirmation,
  deleting,
  onConfirmationChange,
  onCopySlug,
  onCancel,
  onConfirm,
}: TenantDeleteModalProps) {
  if (!tenant) return null;

  return (
    <Modal open onClose={onCancel} title="Удалить тенанта">
      <div className="space-y-5">
        <p className="text-sm text-text-secondary">
          Тенант «{tenant.name}» и его данные будут удалены без возможности восстановления.
        </p>
        <div>
          <label className="mb-1 block text-sm font-medium">Slug тенанта</label>
          <div className="flex gap-2">
            <Input aria-label="Slug тенанта" readOnly value={tenant.slug} className="font-mono" />
            <Button type="button" variant="secondary" onClick={onCopySlug}>
              Копировать
            </Button>
          </div>
        </div>
        <div>
          <label htmlFor="tenant-delete-confirmation" className="mb-1 block text-sm font-medium">
            Вставьте slug для подтверждения
          </label>
          <Input
            id="tenant-delete-confirmation"
            autoComplete="off"
            value={confirmation}
            onChange={(event) => onConfirmationChange(event.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={deleting}>
            Отмена
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={onConfirm}
            disabled={deleting || confirmation !== tenant.slug}
          >
            {deleting ? 'Удаление...' : 'Удалить навсегда'}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
