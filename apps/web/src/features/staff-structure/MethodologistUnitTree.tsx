import { useId, useMemo, useState } from 'react';
import { Building2, ChevronRight, Folder, Network, Search, Users } from 'lucide-react';
import type { StaffWorkspaceUnit } from './StaffWorkspaceClient';
import { WorkspacePanel } from '@/features/workspace-design';

export function MethodologistUnitTree({ units, selected, total, unplaced, onSelect, add }: {
  units: StaffWorkspaceUnit[];
  selected: string;
  total: number;
  unplaced: number;
  onSelect: (id: string) => void;
  add: React.ReactNode;
}) {
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const idPrefix = useId();
  const { byId, children } = useMemo(() => {
    const byId = new Map(units.map((unit) => [unit.id, unit]));
    const children = new Map<string | null, StaffWorkspaceUnit[]>();
    for (const unit of units) {
      const parent = unit.parent_id && byId.has(unit.parent_id) ? unit.parent_id : null;
      const siblings = children.get(parent) ?? [];
      siblings.push(unit);
      children.set(parent, siblings);
    }
    return { byId, children };
  }, [units]);

  const ancestors = (id: string) => {
    const ids = new Set<string>();
    for (let unit = byId.get(id); unit && !ids.has(unit.id); unit = byId.get(unit.parent_id ?? '')) ids.add(unit.id);
    return ids;
  };
  const selectedPath = ancestors(selected);
  const needle = query.trim().toLocaleLowerCase();
  const hits = needle ? units.filter((unit) => [...unit.breadcrumb, unit.name].join(' ').toLocaleLowerCase().includes(needle)) : units;
  const visible = needle ? new Set(hits.flatMap((unit) => [...ancestors(unit.id)])) : null;
  const renderNode = (unit: StaffWorkspaceUnit, path: ReadonlySet<string>) => {
    if (path.has(unit.id) || (visible && !visible.has(unit.id))) return null;
    const nextPath = new Set(path).add(unit.id);
    const nested = (children.get(unit.id) ?? []).filter((child) => !visible || visible.has(child.id));
    const isOpen = Boolean(visible) || (expanded[unit.id] ?? selectedPath.has(unit.id));
    const childId = idPrefix + unit.id;
    return <li key={unit.id} className="mt-1">
      <div className={`flex min-w-0 items-center gap-1 rounded-lg ${selected === unit.id ? 'bg-primary/10' : ''}`}>
        {nested.length > 0 && !visible ? <button type="button" aria-expanded={isOpen} aria-controls={childId}
          aria-label={`${isOpen ? 'Свернуть' : 'Раскрыть'} ${unit.name}`}
          onClick={() => setExpanded((current) => ({ ...current, [unit.id]: !isOpen }))} className="grid size-8 shrink-0 place-items-center rounded text-primary hover:bg-primary/10">
          <ChevronRight className={`h-4 w-4 ${isOpen ? 'rotate-90' : ''}`} aria-hidden="true" />
        </button> : <span className="w-8 shrink-0" />}
        <UnitRow label={unit.name} count={unit.subtree_count} selected={selected === unit.id}
          icon={unit.unit_type === 'branch' ? Building2 : Folder} onClick={() => onSelect(unit.id)} />
      </div>
      {nested.length > 0 && <ul id={childId} hidden={!isOpen} className="ml-4 border-l border-border pl-1">
        {isOpen && nested.map((child) => renderNode(child, nextPath))}
      </ul>}
    </li>;
  };
  return <WorkspacePanel title="Подразделения" actions={add} bodyClassName="space-y-3" aria-label="Дерево подразделений">
    <label className="relative block">
      <span className="sr-only">Поиск подразделений</span>
      <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden="true" />
      <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Филиал или отдел"
        className="h-10 w-full rounded-lg border border-border bg-background pl-9 pr-2 text-sm" />
    </label>
    {!needle && <UnitRow label="Компания" count={Math.max(0, total - unplaced)} selected={selected === 'all'} icon={Network} onClick={() => onSelect('all')} />}
    {hits.length > 0
      ? <ul className="border-l border-border pl-1">{(children.get(null) ?? []).map((unit) => renderNode(unit, new Set()))}</ul>
      : <p role="status" className="text-sm text-muted-foreground">Подразделения не найдены.</p>}
    {!needle && <div className="border-t border-border pt-2">
      <UnitRow label="Без подразделения" count={unplaced} selected={selected === 'unplaced'} icon={Users} onClick={() => onSelect('unplaced')} />
    </div>}
    <p className="text-xs text-muted-foreground">Число у названия показывает сотрудников всей ветки с учётом фильтра доступа.</p>
  </WorkspacePanel>;
}

function UnitRow({ label, count, selected, icon: Icon, onClick }: {
  label: string; count: number; selected: boolean; icon: typeof Building2; onClick: () => void;
}) {
  return <button type="button" aria-pressed={selected} onClick={onClick}
    className={`flex min-h-10 w-full min-w-0 items-center gap-2 rounded-lg px-2 text-left text-sm ${selected ? 'font-semibold text-primary' : 'hover:bg-muted'}`}>
    <Icon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{label}</span>
    <span className="rounded bg-muted px-1.5 text-xs text-muted-foreground">{count}</span>
  </button>;
}
