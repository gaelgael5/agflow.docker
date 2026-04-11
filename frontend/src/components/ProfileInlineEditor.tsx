import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { RoleDetail } from "@/lib/rolesApi";
import type { AgentProfileSummary } from "@/lib/agentsApi";

interface Props {
  profile: AgentProfileSummary;
  roleDetail: RoleDetail | undefined;
  onSave: (doc_ids: string[]) => Promise<void>;
  onClose: () => void;
  onDelete: () => Promise<void>;
}

/**
 * Inline panel (not a popup) for picking which role documents are
 * included in a profile. Documents are grouped by their role section.
 * Any ID in `profile.document_ids` that doesn't match a real document
 * (broken ref) is listed in a red banner at the top so the user can
 * clean up. Selection changes are debounced and auto-saved.
 */
export function ProfileInlineEditor({
  profile,
  roleDetail,
  onSave,
  onClose,
  onDelete,
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

  // Re-sync when switching between profiles without unmounting
  useEffect(() => {
    setSelected(
      new Set(profile.document_ids.filter((id) => validDocIds.has(id))),
    );
    setDirty(false);
  }, [profile.id, profile.document_ids, validDocIds]);

  // Debounced auto-save: 400ms after the last change
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
    <div
      style={{
        marginTop: "0.75rem",
        padding: "1rem",
        background: "#f9fafb",
        border: "1px solid #e5e7eb",
        borderRadius: "4px",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <strong style={{ fontSize: "13px" }}>
          {t("agent_editor.profile_editor_title", { name: profile.name })}
        </strong>
        <span style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <span style={{ fontSize: "11px", color: "#666" }}>
            {saving
              ? t("agent_editor.profile_saving")
              : dirty
                ? t("agent_editor.profile_dirty")
                : t("agent_editor.profile_saved")}
          </span>
          <button
            type="button"
            onClick={() => void onDelete()}
            style={{ color: "red", fontSize: "12px" }}
          >
            {t("agent_editor.profile_delete")}
          </button>
          <button type="button" onClick={onClose} style={{ fontSize: "12px" }}>
            {t("agent_editor.profile_close")}
          </button>
        </span>
      </div>

      {profile.description && (
        <p style={{ color: "#666", fontSize: "12px", margin: "0 0 0.5rem 0" }}>
          {profile.description}
        </p>
      )}

      {brokenIds.length > 0 && (
        <div
          style={{
            padding: "0.5rem 0.75rem",
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            color: "#991b1b",
            fontSize: "12px",
            borderRadius: "4px",
            marginBottom: "0.5rem",
          }}
        >
          {t("agent_editor.profile_broken_refs", { count: brokenIds.length })}
        </div>
      )}

      {(roleDetail?.sections ?? []).map((section) => (
        <div key={section.name} style={{ marginBottom: "0.75rem" }}>
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
            <div
              style={{ fontSize: "12px", color: "#999", fontStyle: "italic" }}
            >
              —
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {section.documents.map((doc) => (
                <label
                  key={doc.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    padding: "3px 0",
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
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
