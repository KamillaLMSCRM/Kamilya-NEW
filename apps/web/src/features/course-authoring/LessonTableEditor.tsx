import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui';
import { tableCellMarkdown, tableCellText, type LessonTable } from './lessonTable';
import { type visualLessonCopy } from './visualLessonCopy';

const inputClass = 'min-w-0 w-full rounded-md border border-input bg-background px-2 py-2 text-base';

export function LessonTableEditor({ table, copy, onChange }: {
  table: LessonTable;
  copy: ReturnType<typeof visualLessonCopy>;
  onChange: (table: LessonTable) => void;
}) {
  const columnCount = Math.max(table.dividers.length, ...table.rows.map(row => row.length));
  const columns = Array.from({ length: columnCount }, (_, index) => index);
  const rows = table.rows.map(row => columns.map(column => row[column] ?? ''));
  const dividers = columns.map(column => table.dividers[column] ?? '---');

  function updateCell(row: number, column: number, text: string) {
    const next = [...rows];
    next[row] = rows[row].map((cell, index) => index === column ? tableCellMarkdown(text) : cell);
    onChange({ rows: next, dividers });
  }

  function removeColumn(column: number) {
    const remove = (row: string[]) => row.filter((_, index) => index !== column);
    onChange({ rows: rows.map(remove), dividers: remove(dividers) });
  }

  return <div className="min-w-0 space-y-2">
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="sm" variant="outline" onClick={() => onChange({ rows: [...rows, columns.map(() => '')], dividers })}>
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />{copy.addRow}
      </Button>
      <Button type="button" size="sm" variant="outline" onClick={() => onChange({ rows: rows.map(row => [...row, '']), dividers: [...dividers, '---'] })}>
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />{copy.addColumn}
      </Button>
    </div>
    <div role="region" aria-label={copy.table} tabIndex={0} className="max-w-full overflow-x-auto rounded-lg border border-border focus-visible:outline focus-visible:outline-primary">
      <table className="w-full border-collapse">
        <thead className="bg-muted/40">
          <tr>
            {columns.map(column => <th key={column} scope="col" className="min-w-36 border-b border-r border-border p-2">
              <div className="flex items-center gap-1">
                <input type="text" className={inputClass} value={tableCellText(rows[0][column])}
                  aria-label={`${copy.tableHeader} ${column + 1}`} placeholder={`${copy.tableHeader} ${column + 1}`}
                  onChange={event => updateCell(0, column, event.target.value)} />
                <Button type="button" size="sm" variant="ghost" disabled={columnCount === 1}
                  aria-label={`${copy.removeColumn} ${column + 1}`} onClick={() => removeColumn(column)}>
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            </th>)}
            <th scope="col" className="border-b border-border"><span className="sr-only">{copy.removeRow}</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(1).map((row, index) => <tr key={index} className="border-b border-border last:border-b-0">
            {row.map((cell, column) => <td key={column} className="border-r border-border p-2">
              <input type="text" className={inputClass} value={tableCellText(cell)}
                aria-label={`${copy.tableCell} ${index + 1}, ${column + 1}`}
                onChange={event => updateCell(index + 1, column, event.target.value)} />
            </td>)}
            <td className="p-1">
              <Button type="button" size="sm" variant="ghost" aria-label={`${copy.removeRow} ${index + 1}`}
                onClick={() => onChange({ rows: rows.filter((_, rowIndex) => rowIndex !== index + 1), dividers })}>
                <Trash2 className="h-4 w-4" aria-hidden="true" />
              </Button>
            </td>
          </tr>)}
        </tbody>
      </table>
    </div>
  </div>;
}
