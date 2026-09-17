export interface OrganizationStructureEmployee {
  id: string;
  full_name: string;
  personnel_number: string | null;
  is_active: boolean;
}

export interface OrganizationStructurePosition {
  id: string;
  name: string;
  department?: string | null;
  department_slug?: string | null;
  department_id?: string | null;
  employee_count: number;
  employees: OrganizationStructureEmployee[];
}

export interface OrganizationUnitNode {
  id: string;
  name: string;
  slug?: string;
  unit_type?: string | null;
  parent_id?: string | null;
  is_active?: boolean;
  is_head_office?: boolean;
  legacy_root?: boolean;
  children: OrganizationUnitNode[];
  positions: OrganizationStructurePosition[];
  department_count?: number;
  position_count?: number;
  employee_count?: number;
}

const UNIT_TYPE_LABELS: Record<string, string> = {
  organization: 'Организация',
  branch: 'Филиал',
  management: 'Управление',
  division: 'Департамент',
  department: 'Отдел',
  sector: 'Сектор',
  team: 'Команда',
  other: 'Другое',
};

export function getOrganizationUnitTypeLabel(unitType: string | null | undefined): string {
  if (!unitType) return 'Подразделение';
  return UNIT_TYPE_LABELS[unitType] || unitType.replace(/[_-]+/g, ' ').replace(/^./, (letter) => letter.toLocaleUpperCase());
}

export function getOrganizationUnitBreadcrumb(nodePath: OrganizationUnitNode[]): string {
  return nodePath.map((node) => node.name).filter(Boolean).join(' → ');
}

export interface FlattenedOrganizationUnit {
  id: string;
  name: string;
  breadcrumb: string;
  depth: number;
  unitType: string;
  isLegacy: boolean;
  node: OrganizationUnitNode;
}

export function flattenOrganizationUnits(
  roots: OrganizationUnitNode[],
  maxDepth = 8,
): FlattenedOrganizationUnit[] {
  const flattened: FlattenedOrganizationUnit[] = [];

  const visit = (node: OrganizationUnitNode, path: OrganizationUnitNode[], depth: number, ancestors: Set<string>) => {
    if (depth >= maxDepth || ancestors.has(node.id)) return;
    const nextPath = [...path, node];
    flattened.push({
      id: node.id,
      name: node.name,
      breadcrumb: getOrganizationUnitBreadcrumb(nextPath),
      depth,
      unitType: getOrganizationUnitTypeLabel(node.unit_type),
      isLegacy: Boolean(node.legacy_root),
      node,
    });
    const nextAncestors = new Set(ancestors);
    nextAncestors.add(node.id);
    node.children.forEach((child) => visit(child, nextPath, depth + 1, nextAncestors));
  };

  roots.forEach((root) => visit(root, [], 0, new Set()));
  return flattened;
}

export function organizationUnitMatches(
  node: OrganizationUnitNode,
  query: string,
): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  if (
    node.name.toLocaleLowerCase().includes(needle)
    || getOrganizationUnitTypeLabel(node.unit_type).toLocaleLowerCase().includes(needle)
    || (node.is_head_office && 'головной офис'.includes(needle))
  ) return true;
  return node.positions.some((position) =>
    position.name.toLocaleLowerCase().includes(needle)
    || position.employees.some((employee) =>
      `${employee.full_name} ${employee.personnel_number || ''}`.toLocaleLowerCase().includes(needle),
    ),
  ) || node.children.some((child) => organizationUnitMatches(child, needle));
}
