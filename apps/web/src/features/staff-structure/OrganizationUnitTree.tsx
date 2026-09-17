"use client";

import Link from 'next/link';
import { BookOpenCheck, Building2, ChevronDown, ChevronRight, GraduationCap } from 'lucide-react';

import { Button, Card, CardContent, CardHeader, CardTitle } from '@/components/ui';

import {
  getOrganizationUnitBreadcrumb,
  getOrganizationUnitTypeLabel,
  organizationUnitMatches,
  type OrganizationStructureEmployee,
  type OrganizationStructurePosition,
  type OrganizationUnitNode,
} from './organizationStructure';

interface OrganizationUnitTreeProps {
  roots: OrganizationUnitNode[];
  query?: string;
  expandedUnitIds: Set<string>;
  expandedPositionIds: Set<string>;
  onToggleUnit: (unitId: string) => void;
  onTogglePosition: (positionId: string) => void;
  onAddChild: (node: OrganizationUnitNode) => void;
  onRename: (node: OrganizationUnitNode) => void;
  onArchive: (node: OrganizationUnitNode) => void;
  onEditEmployee: (employee: OrganizationStructureEmployee) => void;
  title?: string;
  description?: string;
  legacy?: boolean;
}

function positionMatches(position: OrganizationStructurePosition, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return !needle
    || position.name.toLocaleLowerCase().includes(needle)
    || position.employees.some((employee) => `${employee.full_name} ${employee.personnel_number || ''}`.toLocaleLowerCase().includes(needle));
}

function PositionRow({
  position,
  query,
  expanded,
  onToggle,
  onEditEmployee,
}: {
  position: OrganizationStructurePosition;
  query: string;
  expanded: boolean;
  onToggle: () => void;
  onEditEmployee: (employee: OrganizationStructureEmployee) => void;
}) {
  const open = expanded || Boolean(query.trim());
  return (
    <li className="px-4 py-3 pl-12">
      <div className="flex min-w-0 items-start gap-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-start gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />}
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium text-foreground">{position.name}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">{position.employee_count} {position.employee_count === 1 ? 'сотрудник' : 'сотрудников'}</span>
          </span>
        </button>
        <Link href={`/positions/${position.id}?tab=training`} className="shrink-0 rounded-sm text-sm font-medium text-primary hover:underline">
          Профиль и обучение
        </Link>
      </div>
      {open && position.employees.length > 0 && (
        <ul className="mt-2 space-y-1 pl-6">
          {position.employees.map((employee) => <EmployeeRow key={employee.id} employee={employee} onEdit={onEditEmployee} />)}
        </ul>
      )}
    </li>
  );
}

function EmployeeRow({ employee, onEdit }: { employee: OrganizationStructureEmployee; onEdit: (employee: OrganizationStructureEmployee) => void }) {
  return (
    <li className="flex min-w-0 items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-background">
      <span className={employee.is_active ? 'min-w-0 text-base font-semibold text-primary' : 'min-w-0 text-base font-semibold text-muted-foreground line-through'}>
        {employee.full_name}
        {employee.personnel_number && <span className="ml-2 whitespace-nowrap text-xs font-normal text-muted-foreground">· {employee.personnel_number}</span>}
      </span>
      <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={() => onEdit(employee)}>Изменить</Button>
        {employee.is_active && <Link href={`/assignments?user_id=${employee.id}`} className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-primary hover:bg-primary/5"><GraduationCap className="h-4 w-4" aria-hidden="true" /><span className="hidden sm:inline">Назначить обучение</span><span className="sm:hidden">Назначить</span></Link>}
      </span>
    </li>
  );
}

type UnitRowProps = Omit<OrganizationUnitTreeProps, 'roots'>;

function UnitRow({
  node,
  path,
  depth,
  query,
  expandedUnitIds,
  expandedPositionIds,
  onToggleUnit,
  onTogglePosition,
  onAddChild,
  onRename,
  onArchive,
  onEditEmployee,
}: UnitRowProps & { node: OrganizationUnitNode; path: OrganizationUnitNode[]; depth: number }) {
  if (depth > 8) return null;
  const nextPath = [...path, node];
  const matches = organizationUnitMatches(node, query || '');
  if (!matches) return null;
  const hasContent = node.children.length > 0 || node.positions.length > 0;
  const departmentCount = Math.max(node.department_count || 0, node.children.length);
  const positionCount = Math.max(node.position_count || 0, node.positions.length);
  const employeeCount = node.employee_count || 0;
  const open = expandedUnitIds.has(node.id) || Boolean(query?.trim());
  const typeLabel = getOrganizationUnitTypeLabel(node.unit_type);
  const addLabel = node.unit_type === 'branch' ? '+ Добавить отдел' : '+ Добавить подразделение';
  return (
    <li data-testid={`organization-unit-${node.id}`} className="border-b border-border last:border-b-0">
      <div className="flex flex-wrap items-start gap-2 px-4 py-3" style={{ paddingLeft: `${Math.min(depth, 8) * 1.5 + 1}rem` }}>
        <button type="button" onClick={() => onToggleUnit(node.id)} aria-expanded={open} className="flex min-w-0 flex-[1_1_16rem] items-start gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {hasContent ? (open ? <ChevronDown className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />) : <span className="h-4 w-4 shrink-0" aria-hidden="true" />}
          <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2 font-semibold text-foreground"><span>{node.name}</span><span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{typeLabel}</span>{node.is_head_office && <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">Центральный офис</span>}</span>
            <span className="mt-1 block text-xs text-muted-foreground">Путь: {getOrganizationUnitBreadcrumb(nextPath)}</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {departmentCount > 0 && `${departmentCount} ${departmentCount === 1 ? 'отдел' : 'отделов'} · `}
              {positionCount} {positionCount === 1 ? 'должность' : 'должностей'} · {employeeCount} {employeeCount === 1 ? 'сотрудник' : 'сотрудников'}
            </span>
          </span>
        </button>
        <span className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => onAddChild(node)}>{addLabel}</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => onRename(node)}>Переименовать</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => onArchive(node)}>Архивировать</Button>
          {node.id && <Link href={`/training-rules?scope=department&department_id=${node.id}`} className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-foreground hover:bg-background"><BookOpenCheck className="h-4 w-4" aria-hidden="true" /><span className="hidden sm:inline">Обязательные курсы</span></Link>}
        </span>
      </div>
      {open && (
        <div className="bg-muted/20">
          {node.positions.length > 0 && <ul className="divide-y divide-border">{node.positions.filter((position) => positionMatches(position, query || '')).map((position) => <PositionRow key={position.id} position={position} query={query || ''} expanded={expandedPositionIds.has(position.id)} onToggle={() => onTogglePosition(position.id)} onEditEmployee={onEditEmployee} />)}</ul>}
          {node.children.length > 0 && <ul className="divide-y divide-border">{node.children.map((child) => <UnitRow key={child.id} {...{ node: child, path: nextPath, depth: depth + 1, query, expandedUnitIds, expandedPositionIds, onToggleUnit, onTogglePosition, onAddChild, onRename, onArchive, onEditEmployee }} />)}</ul>}
          {!hasContent && <p className="px-12 py-3 text-xs text-muted-foreground">Нет должностей или дочерних подразделений</p>}
        </div>
      )}
    </li>
  );
}

export function OrganizationUnitTree({ roots, title = 'Структура', description, legacy = false, ...props }: OrganizationUnitTreeProps) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle>{description && <p className="text-sm text-muted-foreground">{description}</p>}</CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y divide-border">{roots.map((node) => <UnitRow key={node.id} node={node} path={[]} depth={0} {...props} />)}</ul>
        {legacy && <p className="px-4 py-3 text-xs text-muted-foreground">Это данные совместимого legacy-формата.</p>}
      </CardContent>
    </Card>
  );
}
