import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { MarkdownEditor } from "./MarkdownEditor";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { RoleSummary } from "@/lib/rolesApi";

interface Props {
  role: RoleSummary;
  onRegenerate: () => void;
  regenerating: boolean;
  error: string | null;
}

export function RolePromptTab({
  role,
  onRegenerate,
  regenerating,
  error,
}: Props) {
  const { t } = useTranslation();

  return (
    <div className="max-w-3xl space-y-4">
      <div className="rounded-md bg-primary/5 border-l-4 border-primary p-3 text-[13px] text-foreground/80">
        {t("roles.prompt.explanation")}
      </div>

      <div>
        <Button onClick={onRegenerate} disabled={regenerating}>
          <Sparkles className="w-4 h-4" />
          {regenerating
            ? t("roles.prompt.generating")
            : t("roles.prompt.regenerate_button")}
        </Button>
        {error && (
          <p role="alert" className="text-destructive text-[12px] mt-2">
            {error}
          </p>
        )}
      </div>

      <Card>
        <CardContent className="pt-5">
          <h3 className="text-[14px] font-semibold mb-3">
            {t("roles.prompt.orchestrator_title")}
          </h3>
          {role.prompt_orchestrator_md ? (
            <MarkdownEditor
              value={role.prompt_orchestrator_md}
              onChange={() => {}}
              readOnly
              minHeight={240}
            />
          ) : (
            <p className="text-muted-foreground italic text-[13px]">
              {t("roles.prompt.empty")}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
