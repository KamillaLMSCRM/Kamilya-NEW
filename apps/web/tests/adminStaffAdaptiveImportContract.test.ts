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
    expect(source).not.toContain('legacyImport');
    expect(source).not.toContain('legacyFallback');
  });

  it('makes the no-write-until-approval promise visible and distinguishes unit types', () => {
    expect(source).toContain('authenticatedUi.adminStaff.import.description');
    expect(source).toContain('authenticatedUi.adminStaff.structure.branches');
    expect(source).toContain('authenticatedUi.adminStaff.structure.departments');
    expect(source).toContain('authenticatedUi.adminStaff.structure.addBranch');
    expect(source).toContain('authenticatedUi.adminStaff.structure.addDepartment');
    expect(source).toContain('/v1/organization-units/tree');
    expect(source).toContain('/v1/organization-units');
    expect(source).toContain('needs_mapping');
    expect(source).not.toContain('JSON.stringify(session.workbook_analysis');
    expect(source).not.toMatch(/["'`]\s*(?:Адаптивная|Выбрать файл|Режим загрузки|Предлагаемая структура|Добавить филиал|Добавить отдел|Данные сотрудника)/);
  });
});
