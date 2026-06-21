import React, { useState } from 'react';
import { cn } from '@/lib/utils';

interface TableProps {
  columns: { key: string; label: string }[];
  data: Record<string, any>[];
  onRowClick?: (row: Record<string, any>) => void;
}

export function Table({ columns, data, onRowClick }: TableProps) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="min-w-full divide-y divide-border">
        <thead className="bg-muted">
          <tr>
            {columns.map((col) => (
              <th key={col.key} className="px-4 py-3 text-left text-sm font-medium text-muted-foreground">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.map((row, i) => (
            <tr
              key={i}
              className={cn('hover:bg-muted/50 cursor-pointer', onRowClick && 'cursor-pointer')}
              onClick={() => onRowClick?.(row)}
            >
              {columns.map((col) => (
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
