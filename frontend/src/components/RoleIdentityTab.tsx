import { useTranslation } from "react-i18next";
import { MarkdownEditor } from "./MarkdownEditor";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export function RoleIdentityTab({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div>
      <p>
        <strong>{t("roles.identity.label")}</strong>
      </p>
      <MarkdownEditor
        value={value}
        onChange={onChange}
        placeholder={t("roles.identity.placeholder")}
        minHeight={320}
      />
    </div>
  );
}
