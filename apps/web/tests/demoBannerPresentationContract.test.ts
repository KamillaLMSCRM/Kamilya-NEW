import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(
  resolve(process.cwd(), 'src/components/demo/DemoBanner.tsx'),
  'utf8',
);

describe('demo banner presentation contract', () => {
  it('uses explicit readable colors instead of a theme-dependent warning foreground', () => {
    expect(source).toContain('bg-amber-50');
    expect(source).toContain('text-amber-950');
    expect(source).toContain('dark:bg-amber-950/40');
    expect(source).not.toContain('text-warning-foreground');
  });
});
