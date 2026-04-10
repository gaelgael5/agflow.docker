import { useTranslation } from "react-i18next";

export type IndicatorStatus = "missing" | "empty" | "ok";

interface Props {
  status: IndicatorStatus;
  label: string;
}

const GLYPHS: Record<IndicatorStatus, string> = {
  missing: "🔴",
  empty: "🟠",
  ok: "🟢",
};

export function StatusIndicator({ status, label }: Props) {
  const { t } = useTranslation();
  const title = `${label} — ${t(`status.${status}`)}`;
  return (
    <span role="img" aria-label={title} title={title}>
      {GLYPHS[status]}
    </span>
  );
}
