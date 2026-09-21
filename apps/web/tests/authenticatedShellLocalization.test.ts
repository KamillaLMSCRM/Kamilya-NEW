import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const layoutSource = readFileSync(resolve(process.cwd(), 'src/components/layout/Layout.tsx'), 'utf8');
const sidebarSource = readFileSync(resolve(process.cwd(), 'src/components/layout/Sidebar.tsx'), 'utf8');
const topBarSource = readFileSync(resolve(process.cwd(), 'src/components/layout/TopBar.tsx'), 'utf8');
const commandPaletteSource = readFileSync(resolve(process.cwd(), 'src/components/CommandPalette.tsx'), 'utf8');

describe('authenticated shell localization contract', () => {
  it('uses translated generation toasts and mobile overlay labels', () => {
    expect(layoutSource).toContain("t('toast.generationComplete' as any)");
    expect(layoutSource).toContain("t('toast.generationFailed' as any)");
    expect(layoutSource).toContain("t('toast.generationCancelled' as any)");
    expect(layoutSource).toContain("aria-label={t('sidebar.close')}");
    expect(layoutSource).not.toContain('Курс готов');
    expect(layoutSource).not.toContain('Не удалось сгенерировать курс');
    expect(layoutSource).not.toContain('Генерация отменена');
  });

  it('keeps navigation chrome on translation keys', () => {
    expect(sidebarSource).toContain("t(route.labelKey!)");
    expect(sidebarSource).toContain("t('a11y.mainNavigation')");
    expect(sidebarSource).toContain("t('nav.logout')");
    expect(topBarSource).toContain("t('nav.logout')");
    expect(topBarSource).toContain("t('topbar.impersonationAsSuperadmin')");
    expect(topBarSource).toContain("t('topbar.tenantTitle', { tenant: tenantName })");
    expect(topBarSource).toContain("t('topbar.operatorAria')");
    expect(topBarSource).not.toContain('>Выйти<');
    expect(topBarSource).not.toContain('Вы как суперадмин');
    expect(topBarSource).not.toContain('Войти как оператор платформы');
  });

  it('exposes a localized, accessible command palette dialog', () => {
    expect(commandPaletteSource).toContain('role="dialog"');
    expect(commandPaletteSource).toContain('aria-modal="true"');
    expect(commandPaletteSource).toContain("aria-label={t('topbar.commandPalette')}");
    expect(commandPaletteSource).toContain("aria-label={t('commandPalette.navigation')}");
  });
});
