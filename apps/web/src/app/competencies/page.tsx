"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ExternalLink, Plus, Save, Target } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";
import { useT } from "@/i18n/useT";
import { Button, Input } from "@/components/ui";
import { WorkspacePage, WorkspacePanel } from "@/features/workspace-design";
import { toast } from "@/components/ui/Toast";

type Item = { id: string; name: string; description: string; position_count: number; course_count: number };
type LinkItem = { id: string; name: string };
type Detail = Item & { position_ids: string[]; course_ids: string[] };

export default function CompetenciesPage() {
  const { t, tp } = useT();
  const role = useAuthStore((state) => state.user?.role);
  const allowed = role === "methodologist";
  const [items, setItems] = useState<Item[]>([]);
  const [positions, setPositions] = useState<LinkItem[]>([]);
  const [courses, setCourses] = useState<LinkItem[]>([]);
  const [selected, setSelected] = useState<Detail | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [courseIds, setCourseIds] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [competencies, positionList, courseList] = await Promise.all([
        api.get<Item[]>("/v1/competencies"),
        api.get<any[]>("/v1/positions"),
        api.get<any[]>("/v1/courses"),
      ]);
      setItems(competencies.data);
      setPositions(positionList.data.map((item) => ({ id: item.id, name: item.name })));
      setCourses(courseList.data.map((item) => ({ id: item.id, name: item.title })));
    } catch (error: any) {
      toast.error(t("competencies.loadFailed"), { description: error?.response?.data?.detail || error?.message });
    }
  }, [t]);

  useEffect(() => {
    if (allowed) void load();
  }, [allowed, load]);

  const open = async (item: Item) => {
    try {
      const response = await api.get<Detail>(`/v1/competencies/${item.id}`);
      setSelected(response.data);
      setName(response.data.name);
      setDescription(response.data.description);
      setCourseIds(response.data.course_ids);
    } catch (error: any) {
      toast.error(t("competencies.loadFailed"), { description: error?.response?.data?.detail || error?.message });
    }
  };

  const startNew = () => {
    setSelected(null);
    setName("");
    setDescription("");
    setCourseIds([]);
  };

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const response = await api.post<Detail>("/v1/competencies", { name: name.trim(), description });
      // The identity already exists even if the separate link write fails.
      // Keep it selected so retry saves this competency instead of duplicating it.
      setSelected(response.data);
      if (courseIds.length) {
        await api.put(`/v1/competencies/${response.data.id}/links`, {
          position_ids: [],
          course_ids: courseIds,
        });
      }
      await load();
      await open(response.data);
      toast.success(t("competencies.created"));
    } catch (error: any) {
      toast.error(t("competencies.saveFailed"), { description: error?.response?.data?.detail || error?.message });
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await api.patch(`/v1/competencies/${selected.id}`, { name: name.trim(), description });
      await api.put(`/v1/competencies/${selected.id}/links`, {
        position_ids: selected.position_ids,
        course_ids: courseIds,
      });
      await load();
      toast.success(t("competencies.saved"));
    } catch (error: any) {
      toast.error(t("competencies.saveFailed"), { description: error?.response?.data?.detail || error?.message });
    } finally {
      setSaving(false);
    }
  };

  if (!allowed) return <div className="p-8 text-center text-muted-foreground">{t("competencies.forbidden")}</div>;

  return (
    <WorkspacePage id="competencies" title={t("competencies.title")} description={t("competencies.subtitle")} icon={<Target />} className="mx-auto max-w-7xl px-4 py-6 sm:px-6" actions={<Button className="gap-2" onClick={startNew}><Plus className="h-4 w-4" aria-hidden="true" />{t("competencies.new")}</Button>}>
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(240px,0.35fr)_minmax(0,1fr)]">
        <WorkspacePanel title={t("competencies.title")} bodyClassName="space-y-3 max-h-[36rem] overflow-y-auto">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => void open(item)}
                aria-pressed={selected?.id === item.id}
                className={`w-full rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected?.id === item.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted/50"}`}
              >
                <div className="break-words font-medium">{item.name}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {tp('common.counts.position', item.position_count)} ·{' '}
                  {tp('common.counts.course', item.course_count)}
                </div>
              </button>
            ))}
            {!items.length && <p className="p-3 text-sm text-muted-foreground">{t("competencies.empty")}</p>}
        </WorkspacePanel>
        <div className="min-w-0 space-y-5">
          <WorkspacePanel title={selected?.name || t("competencies.new")}>
            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2 text-sm font-medium">
                {t("competencies.name")}
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t("competencies.namePlaceholder")}
                />
              </label>
              <label className="space-y-2 text-sm font-medium">
                {t("competencies.description")}
                <Input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder={t("competencies.descriptionPlaceholder")}
                />
              </label>
            </div>
          </WorkspacePanel>
            {selected && <ReadOnlyPositions positionIds={selected.position_ids} positions={positions} />}
            <CourseSelector
              title={t("competencies.courses")}
              items={courses}
              selected={courseIds}
              onToggle={(id) =>
                setCourseIds((list) => (list.includes(id) ? list.filter((value) => value !== id) : [...list, id]))
              }
            />
            <div className="flex justify-end">
              <Button
                onClick={() => void (selected ? save() : create())}
                disabled={saving || !name.trim()}
                className="gap-2"
              >
                <Save className="h-4 w-4" />
                {selected ? t("competencies.save") : t("competencies.create")}
              </Button>
            </div>
        </div>
      </div>
    </WorkspacePage>
  );
}

function ReadOnlyPositions({ positionIds, positions }: { positionIds: string[]; positions: LinkItem[] }) {
  const linkedPositions = positionIds.map((id) => positions.find((position) => position.id === id) ?? { id, name: id });
  return (
    <WorkspacePanel title="Связанные должности" description="Требования компетенций задаются в карточке должности.">
      {linkedPositions.length ? (
        <ul className="grid gap-2 sm:grid-cols-2">
          {linkedPositions.map((position) => (
            <li key={position.id}>
              <Link
                href={`/positions/${position.id}?tab=competencies`}
                className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-border px-3 py-3 text-sm hover:bg-muted"
              >
                <span className="min-w-0 truncate">{position.name}</span>
                <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Компетенция пока не связана с должностями.</p>
      )}
    </WorkspacePanel>
  );
}

function CourseSelector({
  title,
  items,
  selected,
  onToggle,
}: {
  title: string;
  items: LinkItem[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  return (
    <WorkspacePanel title={title}>
      <div className="grid gap-2 sm:grid-cols-2">
        {items.map((item) => (
          <label
            key={item.id}
            className={`flex min-w-0 cursor-pointer items-start gap-3 rounded-xl border p-3 ${selected.includes(item.id) ? 'border-primary/30 bg-primary/5' : 'border-border'}`}
          >
            <input type="checkbox" checked={selected.includes(item.id)} onChange={() => onToggle(item.id)} />
            <span className="break-words text-sm">{item.name}</span>
          </label>
        ))}
      </div>
      {!items.length && <p className="text-sm text-muted-foreground">Нет доступных курсов.</p>}
    </WorkspacePanel>
  );
}
