import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { RoleDetail } from "@/lib/rolesApi";
import type { AgentProfileSummary } from "@/lib/agentsApi";

interface Props {
  profile: AgentProfileSummary;
  roleDetail: RoleDetail | undefined;
  onSave: (doc_ids: string[]) => Promise<void>;
  onClose: () => void;
}

/**
 * Dialog for picking which role documents are included in a profile.
 * Documents are grouped by their role section. Any ID in
 * `profile.document_ids` that doesn't match a real document (broken ref)
 * is listed in a red banner at the top so the user can clean up.
 */
export function ProfileEditorDialog({
  profile,
  roleDetail,
  onSave,
  onClose,
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

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll() {
    setSelected(new Set(allDocs.map((d) => d.id)));
  }
  function deselectAll() {
    setSelected(new Set());
  }

  async function handleSave() {
    setSaving(true);
    try {
      await onSave(Array.from(selected));
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        justifyContent: "center",
        alignItems: "flex-start",
        padding: "2rem",
        overflowY: "auto",
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "white",
          padding: "1.5rem",
          maxWidth: 720,
          width: "100%",
          maxHeight: "90vh",
          overflowY: "auto",
          borderRadius: "8px",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: 0 }}>
          {t("agent_editor.profile_editor_title", { name: profile.name })}
        </h2>
        {profile.description && (
          <p style={{ color: "#666", fontSize: "13px" }}>{profile.description}</p>
        )}

        {brokenIds.length > 0 && (
          <div
            style={{
              padding: "0.75rem",
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              color: "#991b1b",
              fontSize: "12px",
              borderRadius: "4px",
              marginTop: "0.5rem",
            }}
          >
            <strong>
              {t("agent_editor.profile_broken_refs", {
                count: brokenIds.length,
              })}
            </strong>
          </div>
        )}

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: "1rem",
            marginBottom: "0.5rem",
          }}
        >
          <strong>{t("agent_editor.profile_editor_pick_docs")}</strong>
          <span style={{ display: "flex", gap: "0.5rem" }}>
            <button type="button" onClick={selectAll}>
              {t("agent_editor.profile_select_all")}
            </button>
            <button type="button" onClick={deselectAll}>
              {t("agent_editor.profile_deselect_all")}
            </button>
          </span>
        </div>

        {(roleDetail?.sections ?? []).map((section) => (
          <div key={section.name} style={{ marginBottom: "1rem" }}>
            <div
              style={{
                fontSize: "11px",
                fontWeight: 600,
                textTransform: "uppercase",
                color: "#666",
                marginBottom: "0.25rem",
              }}
            >
              {section.display_name}
            </div>
            {section.documents.length === 0 ? (
              <div style={{ fontSize: "12px", color: "#999", fontStyle: "italic" }}>
                —
              </div>
            ) : (
              section.documents.map((doc) => (
                <label
                  key={doc.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "4px 0",
                    fontSize: "13px",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(doc.id)}
                    onChange={() => toggle(doc.id)}
                  />
                  <span>{doc.protected ? "🔒" : "📄"}</span>
                  <span>{doc.name}</span>
                </label>
              ))
            )}
          </div>
        ))}

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: "0.5rem",
            marginTop: "1rem",
          }}
        >
          <button type="button" onClick={onClose}>
            {t("agent_editor.cancel")}
          </button>
          <button type="button" onClick={handleSave} disabled={saving}>
            {t("agent_editor.save")}
          </button>
        </div>
      </div>
    </div>
  );
}
