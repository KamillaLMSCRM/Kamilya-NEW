import React from 'react';
import { cn } from '@/lib/utils';

interface TypedTableProps {
  columns: { key: string; label: string }[];
  data: Record<string, any>[];
  onRowClick?: (row: Record<string, any>) => void;
}

interface ChildrenTableProps {
  children: React.ReactNode;
  className?: string;
}

export function Table({ columns, data, onRowClick }: TypedTableProps): JSX.Element;
export function Table({ children, className }: ChildrenTableProps): JSX.Element;
export function Table({ columns, data, onRowClick, children, className }: any) {
  if (children) {
    return (
      <div className={cn('overflow-x-auto rounded-md border', className)}>
        <table className="min-w-full divide-y divide-border">
          {children}
        </table>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="min-w-full divide-y divide-border">
        <thead className="bg-muted">
          <tr>
            {columns.map((col: any) => (
              <th key={col.key} className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.map((row: any, i: number) => (
            <tr
              key={i}
              className={cn('hover:bg-muted/50 cursor-pointer', onRowClick && 'cursor-pointer')}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col: any) => (
                <td key={col.key} className="px-4 py-3 text-sm">
                  {row[col.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
