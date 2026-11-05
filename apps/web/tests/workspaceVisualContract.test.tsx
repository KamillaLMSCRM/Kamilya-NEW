import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import postcss from 'postcss';
import ts from 'typescript';
import tailwindcss from 'tailwindcss';
import tailwindConfig from '../tailwind.config';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Button } from '@/components/ui/button';

const sheet = postcss.parse(readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8'));
function declaration(selector: string, property: string) {
  let value: string | undefined;
  sheet.walkRules((rule) => {
    if (rule.selectors.includes(selector)) rule.walkDecls(property, (decl) => { value = decl.value; });
  });
  return value;
}

describe('production workspace visual contract', () => {
  it('retains dark workspace tokens in generated CSS without a literal dark utility in source content', async () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/globals.css'), 'utf8');
    const built = await postcss([tailwindcss({ ...tailwindConfig, content: [{ raw: '<div data-app-workspace="v1" class="app-workspace bg-background"></div>', extension: 'html' }] })])
      .process(source, { from: undefined });
    const darkRules: string[] = [];
    built.root.walkRules((rule) => {
      rule.walkDecls('--background', (decl) => { if (decl.value === '222 40% 10%') darkRules.push(rule.selector); });
    });
    expect(darkRules).toHaveLength(1);
    expect(darkRules[0]).toContain('[data-app-workspace]');
  });
  it('uses the prototype canvas/ink for the authorized V2 application and authenticated workspace', () => {
    expect(declaration(':root:has([data-app-workspace])', '--background')).toBe('228 33% 97%');
    expect(declaration(':root:has([data-app-workspace])', '--foreground')).toBe('218 43% 16%');
    expect(declaration(':root:has([data-app-workspace])', '--radius')).toBe('0.875rem');
    expect(declaration(':root', '--background')).toBe('36 33% 97%');
    expect(declaration(':root:has([data-design-system="workspace-v2"])', '--background')).toBe('228 33% 97%');
    expect(declaration(':root:has([data-app-workspace])', '--dialog-surface')).toBe('var(--card)');
    expect(declaration(':root', '--dialog-surface')).toBe('var(--background)');
  });

  it('defines an explicit dark counterpart rather than inheriting light-only prototype colours', () => {
    expect(declaration(':root[class~="dark"]:has([data-app-workspace])', '--background')).toBe('222 40% 10%');
    expect(declaration(':root[class~="dark"]:has([data-app-workspace])', '--foreground')).toBe('220 33% 94%');
  });

  it('mounts the production theme marker instead of the decorative grain layer', () => {
    const layout = readFileSync(resolve(process.cwd(), 'src/components/layout/Layout.tsx'), 'utf8');
    expect(layout).toContain('data-app-workspace="v1"');
    expect(layout).not.toContain('bg-background grain');
  });

  it('keeps native button behaviour and exposes stable variant hooks for the theme', () => {
    const save = vi.fn();
    render(<><Button variant="outline" onClick={save}>Save draft</Button><Button disabled>Unavailable</Button></>);
    const button = screen.getByRole('button', { name: 'Save draft' });
    expect(button).toHaveAttribute('data-ui', 'button');
    expect(button).toHaveAttribute('data-ui-variant', 'outline');
    fireEvent.click(button);
    expect(save).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Unavailable' })).toBeDisabled();
  });

  it.each(['ai/generate', 'courses/[id]', 'courses/quiz/[quizId]', 'courses/templates/[blueprintId]'])('uses semantic foregrounds for dark-compatible fills in %s', (route) => {
    const file = ts.createSourceFile(route, readFileSync(resolve(process.cwd(), `src/app/${route}/page.tsx`), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const mismatches: string[] = [];
    function visit(node: ts.Node) {
      if (ts.isStringLiteralLike(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
        const classes = node.text.split(/\s+/);
        if (classes.includes('text-white') && classes.some((name) => ['bg-primary', 'bg-success'].includes(name))) mismatches.push(node.text);
      }
      ts.forEachChild(node, visit);
    }
    visit(file);
    expect(mismatches).toEqual([]);
  });
});
