import { useTranslation } from "react-i18next";
import type { DocumentSummary, Section } from "@/lib/rolesApi";

interface Props {
  documents: DocumentSummary[];
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
  onAdd: (section: Section) => void;
}

const SECTIONS: Section[] = ["roles", "missions", "competences"];

export function RoleSidebar({ documents, selectedDocId, onSelect, onAdd }: Props) {
  const { t } = useTranslation();

  return (
    <aside
      style={{
        minWidth: 260,
        borderRight: "1px solid #ddd",
        padding: "1rem",
      }}
    >
      {SECTIONS.map((section) => {
        const docs = documents.filter((d) => d.section === section);
        const title = t(`roles.sidebar.${section}_section`);
        return (
          <div key={section} style={{ marginBottom: "1.25rem" }}>
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
              <span>{title}</span>
              <button
                type="button"
                onClick={() => onAdd(section)}
                style={{
                  fontSize: "11px",
                  padding: "2px 6px",
                  cursor: "pointer",
                }}
              >
                {t("roles.sidebar.add_document")}
              </button>
            </div>
            {docs.length === 0 ? (
              <div style={{ fontSize: "12px", color: "#999", fontStyle: "italic" }}>
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
    </aside>
  );
}
