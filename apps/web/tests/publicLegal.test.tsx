import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { LegalDocument } from '@/components/legal/LegalDocument';
import { PublicLegalFooter } from '@/components/legal/PublicLegalFooter';

describe('public legal content', () => {
  it('shows the controlled operator details and the B2B-only trial boundary', () => {
    render(<LegalDocument language="ru" kind="terms" />);

    expect(screen.getAllByText(/Document\.KZ/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/080340022947/).length).toBeGreaterThan(0);
    expect(screen.getByText(/не являются публичной офертой/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'askar@kml.kz' })).toHaveAttribute('href', 'mailto:askar@kml.kz');
  });

  it('describes contextual consent and necessary-only cookies', () => {
    render(<LegalDocument language="ru" kind="privacy" />);

    expect(screen.getByText('Кого и какие данные мы обрабатываем')).toBeInTheDocument();
    expect(screen.getByText(/трансграничная обработка может происходить/i)).toBeInTheDocument();
    expect(screen.getByText(/маркетинговые cookies/i)).toBeInTheDocument();
  });

  it('offers both public legal documents and the Kazakh version', () => {
    render(<PublicLegalFooter />);

    expect(screen.getByText(/БИН 080340022947/)).toBeInTheDocument();
    expect(screen.getByText(/Радостовца, дом № 152Л-32/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Уведомление о конфиденциальности' })).toHaveAttribute('href', '/legal/privacy');
    expect(screen.getByRole('link', { name: 'Условия сайта и пробного доступа' })).toHaveAttribute('href', '/legal/terms');
    expect(screen.getByRole('link', { name: 'Қазақша' })).toHaveAttribute('href', '/legal/privacy/kk');
  });
});
