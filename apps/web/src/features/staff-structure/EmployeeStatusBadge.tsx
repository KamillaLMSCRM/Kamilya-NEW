"use client";

import { Badge } from "@/components/ui";
import { useT } from "@/i18n/useT";

export function EmployeeStatusBadge({ isActive }: { isActive: boolean }) {
  const { t } = useT();

  return (
    <Badge
      variant={isActive ? "default" : "outline"}
      className={isActive
        ? "bg-success/15 text-success"
        : "border-muted-foreground/30 bg-muted/50 text-muted-foreground"}
    >
      {isActive
        ? t("authenticatedUi.adminStaff.employee.statusActive")
        : t("authenticatedUi.adminStaff.employee.statusTerminated")}
    </Badge>
  );
}
