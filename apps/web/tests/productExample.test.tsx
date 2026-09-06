import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { ProductExample } from '@/features/product-example/ProductExample';
import { exampleCopy, resolveExampleLanguage } from '@/features/product-example/copy';
import ExamplePage, { generateMetadata } from '@/app/login/example/page';

describe('public learning example contract', () => {
  it.each(['ru', 'kk', 'en', 'unsupported'])('resolves public route and metadata for %s', async lang => {
    const props = { searchParams: Promise.resolve({ lang }) };
    const expected = resolveExampleLanguage(lang);
    expect(await generateMetadata(props)).toEqual({ title: `Kamilya LMS — ${exampleCopy[expected].title}` });
    expect((await ExamplePage(props)).props.language).toBe(expected);
  });
  it.each(['ru', 'kk', 'en'] as const)('shows the complete labeled example in %s without auth or network', language => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(<ProductExample language={language} />);
    const c = exampleCopy[language];
    expect(screen.getByText(c.label)).toBeInTheDocument();
    expect(screen.getByText(c.resultNote)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: c.check })).toBeDisabled();
    c.rows.forEach(row => expect(screen.getByText(row.status)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('radio', { name: c.options[0] }));
    fireEvent.click(screen.getByRole('button', { name: c.check }));
    expect(screen.getByText(c.incorrect)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: c.retry }));
    expect(screen.queryByText(c.incorrect)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: c.check })).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: c.options[1] }));
    fireEvent.click(screen.getByRole('button', { name: c.check }));
    expect(screen.getByText(c.correct)).toBeInTheDocument();
    c.rows.forEach(row => {
      fireEvent.click(screen.getByRole('button', { name: row.action }));
      expect(screen.getByText(row.detail)).toBeInTheDocument();
    });
    expect(screen.getByRole('link', { name: c.demo })).toHaveAttribute('href', '/login/demo');
    expect(screen.getByRole('link', { name: c.trial })).toHaveAttribute('href', '/register-tenant');
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('defaults unsupported and array languages to Russian', () => {
    expect(resolveExampleLanguage('kk')).toBe('kk');
    expect(resolveExampleLanguage('en')).toBe('en');
    for (const value of [undefined, 'xx', ['kk'], '__proto__']) expect(resolveExampleLanguage(value)).toBe('ru');
  });

  it('keeps preview free of API, auth, persistence and tenant dependencies', () => {
    const source = readFileSync('src/features/product-example/ProductExample.tsx', 'utf8');
    expect(source).not.toMatch(/fetch\(|axios|authStore|localStorage|sessionStorage|@\/lib\/api/);
    const page = readFileSync('src/app/login/example/page.tsx', 'utf8');
    expect(page).toContain('resolveExampleLanguage(params.lang)');
  });
});
