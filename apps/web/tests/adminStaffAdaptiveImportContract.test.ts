import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = readFileSync(resolve(process.cwd(), 'src/app/admin/staff/page.tsx'), 'utf8');

describe('adaptive staff import and organization structure contract', () => {
  it('keeps only the adaptive analyze, approve and commit flow in the staff workspace', () => {
    expect(source).toContain('/v1/admin/staff/import/sessions/analyze');
    expect(source).toContain('/approve');
    expect(source).toContain('/commit');
    expect(source).toContain('/mapping');
    expect(source).toContain('mapping_json: adaptiveMapping');
    expect(source).toContain('mapping_id');
    expect(source).not.toContain('/v1/admin/staff/import/preview');
    expect(source).not.toContain('Открыть старый импорт');
    expect(source).not.toContain('Запасной сценарий для прежних файлов');
  });

  it('makes the no-write-until-approval promise visible and distinguishes unit types', () => {
    expect(source).toContain('До вашего подтверждения данные не меняются');
    expect(source).toContain('Филиалы');
    expect(source).toContain('Отделы');
    expect(source).toContain('+ Добавить филиал');
    expect(source).toContain('+ Добавить отдел');
    expect(source).toContain('/v1/organization-units/tree');
    expect(source).toContain('/v1/organization-units');
    expect(source).toContain('needs_mapping');
    expect(source).not.toContain('JSON.stringify(session.workbook_analysis');
  });
});
