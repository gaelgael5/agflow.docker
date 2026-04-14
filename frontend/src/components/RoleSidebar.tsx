import { useTranslation } from "react-i18next";
import { Lock, Plus, Unlock, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  DocumentSummary,
  Section,
  SectionSummary,
} from "@/lib/rolesApi";

export function isDocLocked(doc: DocumentSummary): boolean {
  return doc.name.endsWith("_");
}

export function docDisplayName(doc: DocumentSummary): string {
  return doc.name.endsWith("_") ? doc.name.slice(0, -1) : doc.name;
}

interface Props {
  sections: SectionSummary[];
  documents: DocumentSummary[];
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
  onAdd: (section: Section) => void;
  onAddSection: () => void;
  onDeleteSection: (name: string) => void;
  onToggleLock?: (doc: DocumentSummary) => void;
}

export function RoleSidebar({
  sections,
  documents,
  selectedDocId,
  onSelect,
  onAdd,
  onAddSection,
  onDeleteSection,
  onToggleLock,
}: Props) {
  const { t } = useTranslation();

  return (
    <aside className="hidden md:block w-64 shrink-0 border-r bg-background overflow-y-auto">
      <div className="p-3 space-y-4">
        {sections.map((section) => {
          const docs = documents.filter((d) => d.section === section.name);
          const canDelete = !section.is_native && docs.length === 0;
          return (
            <div key={section.name}>
              <div className="flex items-center justify-between px-1 mb-1">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {section.display_name}
                </span>
                <span className="flex items-center gap-0.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={() => onAdd(section.name)}
                    aria-label={t("roles.sidebar.add_document")}
                  >
                    <Plus className="w-3 h-3" />
                  </Button>
                  {canDelete && (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-5 w-5 text-destructive"
                      onClick={() => onDeleteSection(section.name)}
                      aria-label={t("roles.sidebar.delete_section")}
                    >
                      <X className="w-3 h-3" />
                    </Button>
                  )}
                </span>
              </div>
              {docs.length === 0 ? (
                <div className="text-[12px] text-muted-foreground italic px-2 py-1">
                  —
                </div>
              ) : (
                <ul className="space-y-0.5">
                  {docs.map((doc) => {
                    const active = selectedDocId === doc.id;
                    const locked = isDocLocked(doc);
                    return (
                      <li key={doc.id} className="group">
                        <div className="flex items-center">
                          <button
                            type="button"
                            onClick={() => onSelect(doc.id)}
                            className={cn(
                              "flex-1 text-left flex items-center gap-1.5 px-2 py-1 rounded-md text-[13px] transition-colors",
                              active
                                ? "bg-primary/10 text-primary"
                                : "hover:bg-secondary text-foreground",
                            )}
                          >
                            <span className="truncate">{docDisplayName(doc)}</span>
                          </button>
                          {onToggleLock && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); onToggleLock(doc); }}
                              className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-secondary transition-opacity shrink-0 mr-1"
                              title={locked ? "Déverrouiller" : "Verrouiller"}
                            >
                              {locked ? (
                                <Lock className="w-3 h-3 text-amber-500" />
                              ) : (
                                <Unlock className="w-3 h-3 text-muted-foreground" />
                              )}
                            </button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}

        <Button
          variant="outline"
          size="sm"
          className="w-full border-dashed"
          onClick={onAddSection}
        >
          <Plus className="w-3.5 h-3.5" />
          {t("roles.sidebar.add_section")}
        </Button>
      </div>
    </aside>
  );
}
