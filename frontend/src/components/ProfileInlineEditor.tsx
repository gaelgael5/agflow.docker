import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight } from "lucide-react";
import type { RoleDetail } from "@/lib/rolesApi";
import type { AgentProfileSummary } from "@/lib/agentsApi";
import { cn } from "@/lib/utils";

interface Props {
  profile: AgentProfileSummary;
  roleDetail: RoleDetail | undefined;
  onSave: (doc_ids: string[]) => Promise<void>;
  onClose: () => void;
  onDelete: () => Promise<void>;
}

/**
 * Inline panel (not a popup) for picking which role documents are included
 * in a profile. Documents are grouped by their role section. Any ID in
 * `profile.document_ids` that doesn't match a real document (broken ref)
 * is listed in a red banner at the top so the user can clean up.
 * Selection changes are debounced and auto-saved.
 */
export function ProfileInlineEditor({
  profile,
  roleDetail,
  onSave,
}: Props) {
  const { t } = useTranslation();

  const allDocs = useMemo(
    () => (roleDetail?.sections ?? []).flatMap((s) => s.documents),
    [roleDetail],
  );
  const validDocIds = useMemo(
    () => new Set(allDocs.map((d) => d.id)),
    [allDocs],
  );
  const brokenIds = useMemo(
    () => profile.document_ids.filter((id) => !validDocIds.has(id)),
    [profile.document_ids, validDocIds],
  );

  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(profile.document_ids.filter((id) => validDocIds.has(id))),
  );
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);

  useEffect(() => {
    setSelected(
      new Set(profile.document_ids.filter((id) => validDocIds.has(id))),
    );
    setDirty(false);
  }, [profile.id, profile.document_ids, validDocIds]);

  useEffect(() => {
    if (!dirty) return;
    const handle = setTimeout(async () => {
      setSaving(true);
      try {
        await onSave(Array.from(selected));
        setDirty(false);
      } finally {
        setSaving(false);
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [dirty, selected, onSave]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setDirty(true);
  }

  return (
    <div className="mt-3 pt-3 border-t">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-muted-foreground">
          {saving
            ? t("agent_editor.profile_saving")
            : dirty
              ? t("agent_editor.profile_dirty")
              : t("agent_editor.profile_saved")}
        </span>
      </div>

      {brokenIds.length > 0 && (
        <div className="rounded-md bg-destructive/5 border border-destructive/30 text-destructive p-2.5 text-[12px] mb-3">
          {t("agent_editor.profile_broken_refs", { count: brokenIds.length })}
        </div>
      )}

      {(roleDetail?.sections ?? []).map((section) => (
        <div key={section.name} className="mb-3">
          <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">
            {section.display_name}
          </div>
          {section.documents.length === 0 ? (
            <div className="text-[12px] text-muted-foreground italic">—</div>
          ) : (
            <div className="flex flex-col">
              {section.documents.map((doc) => (
                <div key={doc.id}>
                  <div className="flex items-center gap-1.5 py-1 hover:bg-secondary/30 rounded px-1 -mx-1">
                    <input
                      type="checkbox"
                      checked={selected.has(doc.id)}
                      onChange={() => toggle(doc.id)}
                      className="accent-primary cursor-pointer"
                    />
                    <button
                      type="button"
                      className="flex items-center gap-1 text-[13px] cursor-pointer flex-1 min-w-0 text-left"
                      onClick={() => setExpandedDoc(expandedDoc === doc.id ? null : doc.id)}
                    >
                      <ChevronRight className={cn(
                        "w-3 h-3 shrink-0 transition-transform text-muted-foreground",
                        expandedDoc === doc.id && "rotate-90",
                      )} />
                      <span className="truncate">{doc.name}</span>
                    </button>
                  </div>
                  {expandedDoc === doc.id && doc.content_md && (
                    <div className="ml-7 mb-2 p-2 rounded bg-muted text-[11px] text-muted-foreground whitespace-pre-wrap max-h-40 overflow-y-auto">
                      {doc.content_md}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
