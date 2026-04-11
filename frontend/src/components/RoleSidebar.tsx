import { useTranslation } from "react-i18next";
import type {
  DocumentSummary,
  Section,
  SectionSummary,
} from "@/lib/rolesApi";

interface Props {
  sections: SectionSummary[];
  documents: DocumentSummary[];
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
  onAdd: (section: Section) => void;
  onAddSection: () => void;
  onDeleteSection: (name: string) => void;
}

export function RoleSidebar({
  sections,
  documents,
  selectedDocId,
  onSelect,
  onAdd,
  onAddSection,
  onDeleteSection,
}: Props) {
  const { t } = useTranslation();

  return (
    <aside
      style={{
        minWidth: 260,
        borderRight: "1px solid #ddd",
        padding: "1rem",
      }}
    >
      {sections.map((section) => {
        const docs = documents.filter((d) => d.section === section.name);
        const canDelete = !section.is_native && docs.length === 0;
        return (
          <div key={section.name} style={{ marginBottom: "1.25rem" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontWeight: 600,
                fontSize: "11px",
                letterSpacing: "0.05em",
                color: "#666",
                marginBottom: "0.5rem",
              }}
            >
              <span style={{ textTransform: "uppercase" }}>
                {section.display_name}
              </span>
              <span style={{ display: "flex", gap: "0.25rem" }}>
                <button
                  type="button"
                  onClick={() => onAdd(section.name)}
                  title={t("roles.sidebar.add_document")}
                  style={{
                    fontSize: "11px",
                    padding: "2px 6px",
                    cursor: "pointer",
                  }}
                >
                  +
                </button>
                {canDelete && (
                  <button
                    type="button"
                    onClick={() => onDeleteSection(section.name)}
                    title={t("roles.sidebar.delete_section")}
                    style={{
                      fontSize: "11px",
                      padding: "2px 6px",
                      cursor: "pointer",
                      color: "#c00",
                    }}
                  >
                    ×
                  </button>
                )}
              </span>
            </div>
            {docs.length === 0 ? (
              <div
                style={{ fontSize: "12px", color: "#999", fontStyle: "italic" }}
              >
                —
              </div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {docs.map((doc) => (
                  <li key={doc.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(doc.id)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.5rem",
                        width: "100%",
                        padding: "4px 6px",
                        textAlign: "left",
                        border: "none",
                        background:
                          selectedDocId === doc.id ? "#e0e7ff" : "transparent",
                        cursor: "pointer",
                        fontSize: "13px",
                      }}
                    >
                      <span>{doc.protected ? "🔒" : "📄"}</span>
                      <span>{doc.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}

      <button
        type="button"
        onClick={onAddSection}
        style={{
          width: "100%",
          marginTop: "0.5rem",
          padding: "6px",
          fontSize: "12px",
          border: "1px dashed #ccc",
          background: "transparent",
          cursor: "pointer",
          color: "#666",
        }}
      >
        {t("roles.sidebar.add_section")}
      </button>
    </aside>
  );
}
