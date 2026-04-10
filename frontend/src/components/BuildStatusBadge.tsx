import { useTranslation } from "react-i18next";
import type { DisplayStatus } from "@/lib/dockerfilesApi";

interface Props {
  status: DisplayStatus;
}

export function BuildStatusBadge({ status }: Props) {
  const { t } = useTranslation();
  return (
    <span style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
      {t(`dockerfiles.status.${status}`)}
    </span>
  );
}
