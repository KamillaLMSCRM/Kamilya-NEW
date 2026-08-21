import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const coursesPage = readFileSync(resolve(process.cwd(), 'src/app/courses/page.tsx'), 'utf8');
const blueprintPage = readFileSync(
  resolve(process.cwd(), 'src/app/courses/templates/[blueprintId]/page.tsx'),
  'utf8',
);

describe('compliance blueprint catalogue UI contract', () => {
  it('requests and renders the server catalog instead of a finance-only offer', () => {
    expect(coursesPage).toContain('/v1/course-blueprints?locale=');
    expect(coursesPage).toContain('blueprints.map');
    expect(coursesPage).toContain('/courses/templates/${encodeURIComponent(blueprint.id)}');
    expect(coursesPage).toContain('blueprint.compliance_mode');
    expect(coursesPage).toContain('blueprint.applicability');
    expect(coursesPage).toContain('/courses/templates/${encodeURIComponent(blueprint.id)}');
  });

  it('keeps loading, error, and empty catalog behavior explicit', () => {
    expect(coursesPage).toContain('setBlueprints');
    expect(coursesPage).toContain('loading');
    expect(coursesPage).toContain('loadError');
    expect(coursesPage).toContain('blueprints.length === 0');
    expect(coursesPage).toContain('LoadError');
  });

  it('renders server-provided adaptation labels, placeholders, and compliance metadata', () => {
    expect(blueprintPage).toContain('item.title');
    expect(blueprintPage).toContain('item.description');
    expect(blueprintPage).toContain('item.answer_placeholder');
    expect(blueprintPage).toContain('blueprint.compliance_mode');
    expect(blueprintPage).toContain('blueprint.applicability');
    expect(blueprintPage).toContain('blueprint.limitations.map');
  });
});
