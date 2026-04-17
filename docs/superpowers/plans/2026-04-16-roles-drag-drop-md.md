# Drag-and-drop `.md` dans les sections de Rôle — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à l'utilisateur de glisser-déposer un ou plusieurs fichiers `.md` depuis son OS sur une section de la sidebar Rôles, pour créer les documents correspondants (avec gestion de conflit de nom).

**Architecture:** Frontend uniquement — aucune migration DB, aucun nouvel endpoint. Les routes existantes `POST/PUT /admin/roles/{id}/documents` suffisent. On ajoute : un hook HTML5 drag-drop natif, 3 helpers purs (validation, sanitize, free-name), un dialog de résolution de conflit, et on câble le tout dans `RoleSidebar` + `RolesPage`.

**Tech Stack:** React 18 + TypeScript strict, Vitest + React Testing Library, shadcn/ui (Dialog, Button), sonner (toasts), TanStack Query (mutations existantes), i18next (FR + EN). Pas de `react-dropzone`.

**Spec de référence:** `docs/superpowers/specs/2026-04-16-roles-drag-drop-md-design.md`

---

## File Structure

**Créés (code) :**
- `frontend/src/lib/dropFiles.ts` — 3 fonctions pures (validation, sanitize du nom, recherche de nom libre)
- `frontend/src/hooks/useSectionDropzone.ts` — hook HTML5 drag-drop par section
- `frontend/src/components/DropConflictDialog.tsx` — dialog shadcn 3 boutons + "appliquer à tous"

**Créés (tests) :**
- `frontend/tests/lib/dropFiles.test.ts`
- `frontend/tests/hooks/useSectionDropzone.test.tsx`
- `frontend/tests/components/DropConflictDialog.test.tsx`

**Modifiés :**
- `frontend/src/components/RoleSidebar.tsx` — câble le dropzone + highlight par section
- `frontend/src/pages/RolesPage.tsx` — `handleDropFiles()` : validation, dialog conflit, boucle mutations, toast
- `frontend/src/i18n/fr.json`, `frontend/src/i18n/en.json` — clés `roles.drop.*`
- `frontend/tests/components/RoleSidebar.test.tsx` — scénarios drag-over + drop
- `frontend/tests/pages/RolesPage.test.tsx` — scénarios batch, conflit, erreurs (créer si absent)

---

## Task 1 : Helpers purs dans `lib/dropFiles.ts`

**Files:**
- Create: `frontend/src/lib/dropFiles.ts`
- Test: `frontend/tests/lib/dropFiles.test.ts`

**Pourquoi d'abord :** 3 fonctions pures, faciles à tester, réutilisées par toutes les tâches suivantes.

- [ ] **Step 1.1 : Écrire le fichier de tests**

Créer `frontend/tests/lib/dropFiles.test.ts` :

```ts
import { describe, it, expect } from "vitest";
import {
  isMarkdownFile,
  sanitizeDocName,
  findFreeName,
  MAX_FILE_SIZE_BYTES,
} from "@/lib/dropFiles";

describe("isMarkdownFile", () => {
  it("accepts .md files (case-insensitive)", () => {
    expect(isMarkdownFile(new File([""], "foo.md"))).toBe(true);
    expect(isMarkdownFile(new File([""], "FOO.MD"))).toBe(true);
    expect(isMarkdownFile(new File([""], "Mixed.Md"))).toBe(true);
  });

  it("rejects non-.md extensions", () => {
    expect(isMarkdownFile(new File([""], "foo.txt"))).toBe(false);
    expect(isMarkdownFile(new File([""], "foo.pdf"))).toBe(false);
    expect(isMarkdownFile(new File([""], "foo"))).toBe(false);
  });
});

describe("sanitizeDocName", () => {
  it("strips extension and slugifies", () => {
    expect(sanitizeDocName("Mission Audit.md")).toBe("mission-audit");
    expect(sanitizeDocName("Élève — rôle.md")).toBe("eleve-role");
  });

  it("returns empty string for invalid names", () => {
    expect(sanitizeDocName(".md")).toBe("");
    expect(sanitizeDocName("---.md")).toBe("");
    expect(sanitizeDocName("")).toBe("");
  });

  it("keeps existing hyphens and digits", () => {
    expect(sanitizeDocName("mission-v2.md")).toBe("mission-v2");
    expect(sanitizeDocName("step_1.md")).toBe("step_1");
  });
});

describe("findFreeName", () => {
  it("returns the original name when free", () => {
    expect(findFreeName("mission", ["other", "doc"])).toBe("mission");
  });

  it("suffixes -2, -3 until free", () => {
    expect(findFreeName("mission", ["mission"])).toBe("mission-2");
    expect(findFreeName("mission", ["mission", "mission-2"])).toBe("mission-3");
    expect(findFreeName("mission", ["mission", "mission-2", "mission-3"])).toBe("mission-4");
  });
});

describe("MAX_FILE_SIZE_BYTES", () => {
  it("equals 1 MiB", () => {
    expect(MAX_FILE_SIZE_BYTES).toBe(1024 * 1024);
  });
});
```

- [ ] **Step 1.2 : Exécuter les tests, vérifier qu'ils échouent**

Run: `cd frontend && npx vitest run tests/lib/dropFiles.test.ts`
Expected: FAIL — module introuvable.

- [ ] **Step 1.3 : Créer `lib/dropFiles.ts`**

```ts
import { slugify } from "@/lib/slugify";

export const MAX_FILE_SIZE_BYTES = 1024 * 1024;

export function isMarkdownFile(file: File): boolean {
  return /\.md$/i.test(file.name);
}

export function sanitizeDocName(filename: string): string {
  const base = filename.replace(/\.md$/i, "");
  return slugify(base, "-");
}

export function findFreeName(candidate: string, existing: readonly string[]): string {
  const taken = new Set(existing);
  if (!taken.has(candidate)) return candidate;
  let i = 2;
  while (taken.has(`${candidate}-${i}`)) i += 1;
  return `${candidate}-${i}`;
}
```

- [ ] **Step 1.4 : Re-exécuter les tests, vérifier qu'ils passent**

Run: `cd frontend && npx vitest run tests/lib/dropFiles.test.ts`
Expected: PASS — 10 tests verts.

- [ ] **Step 1.5 : Commit**

```bash
git add frontend/src/lib/dropFiles.ts frontend/tests/lib/dropFiles.test.ts
git commit -m "test(roles): helpers purs pour drop de fichiers .md"
```

---

## Task 2 : Hook `useSectionDropzone`

**Files:**
- Create: `frontend/src/hooks/useSectionDropzone.ts`
- Test: `frontend/tests/hooks/useSectionDropzone.test.tsx`

- [ ] **Step 2.1 : Écrire les tests**

Créer `frontend/tests/hooks/useSectionDropzone.test.tsx` :

```tsx
import { describe, it, expect, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSectionDropzone } from "@/hooks/useSectionDropzone";

function makeDragEvent(type: string, files: File[] = []): unknown {
  return {
    type,
    preventDefault: vi.fn(),
    stopPropagation: vi.fn(),
    dataTransfer: { files, types: ["Files"] },
  };
}

describe("useSectionDropzone", () => {
  it("is not dragOver initially", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    expect(result.current.isDragOver).toBe(false);
  });

  it("sets isDragOver on dragenter with Files", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDragEnter(makeDragEvent("dragenter") as never);
    });
    expect(result.current.isDragOver).toBe(true);
  });

  it("clears isDragOver on dragleave", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDragEnter(makeDragEvent("dragenter") as never);
    });
    act(() => {
      result.current.dropzoneProps.onDragLeave(makeDragEvent("dragleave") as never);
    });
    expect(result.current.isDragOver).toBe(false);
  });

  it("calls onFiles on drop with the FileList and clears state", () => {
    const onFiles = vi.fn();
    const files = [new File(["# hi"], "a.md")];
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    act(() => {
      result.current.dropzoneProps.onDrop(makeDragEvent("drop", files) as never);
    });
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect(onFiles).toHaveBeenCalledWith(files);
    expect(result.current.isDragOver).toBe(false);
  });

  it("calls preventDefault on dragover to enable drop", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useSectionDropzone(onFiles));
    const evt = makeDragEvent("dragover");
    act(() => {
      result.current.dropzoneProps.onDragOver(evt as never);
    });
    expect((evt as { preventDefault: () => void }).preventDefault).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2.2 : Exécuter, vérifier fail**

Run: `cd frontend && npx vitest run tests/hooks/useSectionDropzone.test.tsx`
Expected: FAIL — module introuvable.

- [ ] **Step 2.3 : Créer le hook**

Créer `frontend/src/hooks/useSectionDropzone.ts` :

```ts
import { useCallback, useState, type DragEvent } from "react";

export function useSectionDropzone(onFiles: (files: File[]) => void) {
  const [isDragOver, setIsDragOver] = useState(false);

  const onDragEnter = useCallback((e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types.includes("Files")) {
      setIsDragOver(true);
    }
  }, []);

  const onDragOver = useCallback((e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const onDragLeave = useCallback((e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const onDrop = useCallback(
    (e: DragEvent<HTMLElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) onFiles(files);
    },
    [onFiles],
  );

  return {
    isDragOver,
    dropzoneProps: { onDragEnter, onDragOver, onDragLeave, onDrop },
  };
}
```

- [ ] **Step 2.4 : Re-exécuter, vérifier pass**

Run: `cd frontend && npx vitest run tests/hooks/useSectionDropzone.test.tsx`
Expected: PASS — 5 tests verts.

- [ ] **Step 2.5 : Commit**

```bash
git add frontend/src/hooks/useSectionDropzone.ts frontend/tests/hooks/useSectionDropzone.test.tsx
git commit -m "feat(roles): hook useSectionDropzone pour drag-drop natif"
```

---

## Task 3 : Clés i18n FR + EN

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 3.1 : Ajouter le bloc `drop` sous `roles` dans `fr.json`**

Repérer la fin du bloc `roles.sidebar` (cherche `"sidebar": {` jusqu'à sa fermeture) puis ajouter un bloc frère `drop`. Exemple :

```json
    "drop": {
      "hint": "Déposer des fichiers .md ici",
      "confirm_batch_title": "Importer {{count}} fichiers",
      "confirm_batch_message": "Importer {{count}} fichiers dans la section « {{section}} » ?",
      "confirm_batch_confirm": "Importer",
      "conflict_title": "Document déjà existant",
      "conflict_message": "Le document « {{name}} » existe déjà dans « {{section}} ». Que faire ?",
      "conflict_replace": "Remplacer",
      "conflict_rename": "Renommer ({{suggested}})",
      "conflict_cancel": "Ignorer ce fichier",
      "conflict_apply_all": "Appliquer à tous les conflits de ce lot",
      "toast_success": "{{count}} document(s) créé(s) dans {{section}}",
      "toast_replaced": "{{count}} document(s) remplacé(s) dans {{section}}",
      "toast_mixed": "{{created}} créés, {{replaced}} remplacés, {{failed}} échoués",
      "toast_none": "Aucun document créé",
      "error_extension": "{{name}} ignoré — seul le format .md est accepté",
      "error_size": "{{name}} ignoré — taille supérieure à 1 Mio",
      "error_encoding": "{{name}} ignoré — encodage non UTF-8",
      "error_name": "{{name}} ignoré — nom de document invalide après normalisation",
      "error_network": "{{name}} — échec réseau"
    }
```

- [ ] **Step 3.2 : Miroir anglais dans `en.json`**

```json
    "drop": {
      "hint": "Drop .md files here",
      "confirm_batch_title": "Import {{count}} files",
      "confirm_batch_message": "Import {{count}} files into section \"{{section}}\"?",
      "confirm_batch_confirm": "Import",
      "conflict_title": "Document already exists",
      "conflict_message": "Document \"{{name}}\" already exists in \"{{section}}\". What would you like to do?",
      "conflict_replace": "Replace",
      "conflict_rename": "Rename ({{suggested}})",
      "conflict_cancel": "Skip this file",
      "conflict_apply_all": "Apply to all conflicts in this batch",
      "toast_success": "{{count}} document(s) created in {{section}}",
      "toast_replaced": "{{count}} document(s) replaced in {{section}}",
      "toast_mixed": "{{created}} created, {{replaced}} replaced, {{failed}} failed",
      "toast_none": "No documents created",
      "error_extension": "{{name}} skipped — only .md is accepted",
      "error_size": "{{name}} skipped — size exceeds 1 MiB",
      "error_encoding": "{{name}} skipped — non-UTF-8 encoding",
      "error_name": "{{name}} skipped — invalid document name after normalization",
      "error_network": "{{name}} — network error"
    }
```

- [ ] **Step 3.3 : Vérifier que les deux JSON parsent**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json')); JSON.parse(require('fs').readFileSync('src/i18n/en.json')); console.log('OK')"`
Expected: `OK`

- [ ] **Step 3.4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(roles): clés i18n FR/EN pour drag-drop .md"
```

---

## Task 4 : Composant `DropConflictDialog`

**Files:**
- Create: `frontend/src/components/DropConflictDialog.tsx`
- Test: `frontend/tests/components/DropConflictDialog.test.tsx`

- [ ] **Step 4.1 : Écrire les tests**

Créer `frontend/tests/components/DropConflictDialog.test.tsx` :

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { DropConflictDialog } from "@/components/DropConflictDialog";

function renderDialog(overrides = {}) {
  const props = {
    open: true,
    name: "mission-audit",
    section: "missions",
    suggestedRename: "mission-audit-2",
    onResolve: vi.fn(),
    onOpenChange: vi.fn(),
    ...overrides,
  };
  render(
    <I18nextProvider i18n={i18n}>
      <DropConflictDialog {...props} />
    </I18nextProvider>,
  );
  return props;
}

describe("DropConflictDialog", () => {
  it("renders the conflict message with the doc name and section", () => {
    renderDialog();
    expect(screen.getByText(/mission-audit/)).toBeInTheDocument();
    expect(screen.getByText(/missions/)).toBeInTheDocument();
  });

  it("calls onResolve({action: 'replace', applyToAll: false}) on Replace click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /remplacer|replace/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "replace", applyToAll: false });
  });

  it("calls onResolve({action: 'rename', applyToAll: false}) with suggestion on Rename click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /renommer|rename/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "rename", applyToAll: false });
  });

  it("calls onResolve({action: 'cancel', applyToAll: false}) on Cancel click", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /ignorer|skip/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "cancel", applyToAll: false });
  });

  it("propagates applyToAll=true when the checkbox is checked", () => {
    const { onResolve } = renderDialog();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /remplacer|replace/i }));
    expect(onResolve).toHaveBeenCalledWith({ action: "replace", applyToAll: true });
  });
});
```

- [ ] **Step 4.2 : Exécuter, vérifier fail**

Run: `cd frontend && npx vitest run tests/components/DropConflictDialog.test.tsx`
Expected: FAIL — module introuvable.

- [ ] **Step 4.3 : Créer le composant**

Créer `frontend/src/components/DropConflictDialog.tsx` :

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

export type ConflictAction = "replace" | "rename" | "cancel";

export interface ConflictResolution {
  action: ConflictAction;
  applyToAll: boolean;
}

interface Props {
  open: boolean;
  name: string;
  section: string;
  suggestedRename: string;
  onResolve: (resolution: ConflictResolution) => void;
  onOpenChange: (open: boolean) => void;
}

export function DropConflictDialog({
  open,
  name,
  section,
  suggestedRename,
  onResolve,
  onOpenChange,
}: Props) {
  const { t } = useTranslation();
  const [applyToAll, setApplyToAll] = useState(false);

  const resolve = (action: ConflictAction) => {
    onResolve({ action, applyToAll });
    setApplyToAll(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("roles.drop.conflict_title")}</DialogTitle>
          <DialogDescription>
            {t("roles.drop.conflict_message", { name, section })}
          </DialogDescription>
        </DialogHeader>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={applyToAll}
            onChange={(e) => setApplyToAll(e.target.checked)}
          />
          {t("roles.drop.conflict_apply_all")}
        </label>

        <DialogFooter className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={() => resolve("cancel")}>
            {t("roles.drop.conflict_cancel")}
          </Button>
          <Button variant="outline" onClick={() => resolve("rename")}>
            {t("roles.drop.conflict_rename", { suggested: suggestedRename })}
          </Button>
          <Button onClick={() => resolve("replace")}>
            {t("roles.drop.conflict_replace")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4.4 : Re-exécuter, vérifier pass**

Run: `cd frontend && npx vitest run tests/components/DropConflictDialog.test.tsx`
Expected: PASS — 5 tests verts.

- [ ] **Step 4.5 : Commit**

```bash
git add frontend/src/components/DropConflictDialog.tsx frontend/tests/components/DropConflictDialog.test.tsx
git commit -m "feat(roles): DropConflictDialog (remplacer/renommer/ignorer)"
```

---

## Task 5 : Câblage dropzone dans `RoleSidebar`

**Files:**
- Modify: `frontend/src/components/RoleSidebar.tsx`
- Modify: `frontend/tests/components/RoleSidebar.test.tsx`

- [ ] **Step 5.1 : Ajouter les tests dans `RoleSidebar.test.tsx`**

Cherche le `describe("RoleSidebar", ...)` existant et ajoute à la fin :

```tsx
  it("highlights only the section being dragged over", () => {
    const onFilesDropped = vi.fn();
    render(<RoleSidebar {...baseProps} onFilesDropped={onFilesDropped} />);
    const missionsZone = screen.getByTestId("section-dropzone-missions");
    fireEvent.dragEnter(missionsZone, {
      dataTransfer: { types: ["Files"], files: [] },
    });
    expect(missionsZone).toHaveClass("ring-2");
    const competencesZone = screen.getByTestId("section-dropzone-competences");
    expect(competencesZone).not.toHaveClass("ring-2");
  });

  it("calls onFilesDropped(sectionName, files) on drop", () => {
    const onFilesDropped = vi.fn();
    render(<RoleSidebar {...baseProps} onFilesDropped={onFilesDropped} />);
    const file = new File(["# hello"], "mission.md");
    const missionsZone = screen.getByTestId("section-dropzone-missions");
    fireEvent.drop(missionsZone, {
      dataTransfer: { types: ["Files"], files: [file] },
    });
    expect(onFilesDropped).toHaveBeenCalledWith("missions", [file]);
  });
```

(`baseProps` doit déjà contenir au minimum des sections `missions` et `competences` ; sinon ajoute-les dans les props mockées existantes.)

- [ ] **Step 5.2 : Exécuter, vérifier fail**

Run: `cd frontend && npx vitest run tests/components/RoleSidebar.test.tsx`
Expected: FAIL — soit `onFilesDropped` non-reconnu par TS, soit `data-testid` introuvable.

- [ ] **Step 5.3 : Modifier `RoleSidebar.tsx`**

Ajouter en haut du fichier :

```tsx
import { useSectionDropzone } from "@/hooks/useSectionDropzone";
```

Ajouter le prop dans `interface Props` :

```tsx
  onFilesDropped?: (section: Section, files: File[]) => void;
```

Déstructurer le prop dans `RoleSidebar({...})`.

Refactorer la boucle `sections.map(...)` en extrayant le rendu d'une section dans un sous-composant local pour pouvoir appeler le hook à l'intérieur (React interdit les hooks dans une boucle sans composant dédié) :

```tsx
function SectionDropzone({
  section,
  children,
  onFiles,
}: {
  section: Section;
  children: React.ReactNode;
  onFiles?: (section: Section, files: File[]) => void;
}) {
  const { isDragOver, dropzoneProps } = useSectionDropzone(
    (files) => onFiles?.(section, files),
  );
  return (
    <div
      data-testid={`section-dropzone-${section}`}
      className={cn(
        "rounded-md transition-colors",
        isDragOver && "ring-2 ring-green-500 bg-green-500/10",
      )}
      {...dropzoneProps}
    >
      {children}
    </div>
  );
}
```

Puis encadrer chaque itération de `sections.map((section) => { ... <div key={section.name}>...</div> ... })` avec `<SectionDropzone section={section.name} onFiles={onFilesDropped}> ... </SectionDropzone>` (le `key={section.name}` reste sur le wrapper `SectionDropzone`).

- [ ] **Step 5.4 : Re-exécuter, vérifier pass**

Run: `cd frontend && npx vitest run tests/components/RoleSidebar.test.tsx`
Expected: PASS — tests historiques + 2 nouveaux verts.

- [ ] **Step 5.5 : Commit**

```bash
git add frontend/src/components/RoleSidebar.tsx frontend/tests/components/RoleSidebar.test.tsx
git commit -m "feat(roles): câblage dropzone par section dans RoleSidebar"
```

---

## Task 6 : Orchestration `handleDropFiles` dans `RolesPage`

**Files:**
- Modify: `frontend/src/pages/RolesPage.tsx`
- Test: `frontend/tests/pages/RolesPage.test.tsx` (créer si absent)

- [ ] **Step 6.1 : Écrire les tests (scénarios critiques)**

Créer ou enrichir `frontend/tests/pages/RolesPage.test.tsx` avec ces 5 blocs :

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter } from "react-router-dom";
import i18n from "@/lib/i18n";
import { RolesPage } from "@/pages/RolesPage";
import { rolesApi } from "@/lib/rolesApi";

vi.mock("@/lib/rolesApi", () => ({
  rolesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generatePrompts: vi.fn(),
    exportZip: vi.fn(),
    importZip: vi.fn(),
    listDocs: vi.fn(),
    createDoc: vi.fn(),
    updateDoc: vi.fn(),
    removeDoc: vi.fn(),
    createSection: vi.fn(),
    removeSection: vi.fn(),
  },
}));

const ROLE_FIXTURE = {
  id: "role-1",
  display_name: "Architect",
  identity_md: "",
  sections: [
    { name: "missions", display_name: "MISSIONS", is_native: true, position: 1 },
    { name: "competences", display_name: "COMPETENCES", is_native: true, position: 2 },
  ],
  documents: [
    { id: "d1", role_id: "role-1", section: "missions", name: "existing", content_md: "old", protected: false },
  ],
};

function setup() {
  vi.mocked(rolesApi.list).mockResolvedValue([{ id: "role-1", display_name: "Architect" }]);
  vi.mocked(rolesApi.get).mockResolvedValue(ROLE_FIXTURE);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>
          <RolesPage />
        </MemoryRouter>
      </I18nextProvider>
    </QueryClientProvider>,
  );
}

async function selectRole() {
  // ouvre le Select et clique sur "Architect" ; adapte selon l'impl shadcn/Select.
  fireEvent.click(await screen.findByRole("combobox"));
  fireEvent.click(await screen.findByText("Architect"));
}

function dropFiles(section: string, files: File[]) {
  const zone = screen.getByTestId(`section-dropzone-${section}`);
  fireEvent.drop(zone, { dataTransfer: { types: ["Files"], files } });
}

describe("RolesPage drag-drop", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rejects a non-.md file and does not call createDoc", async () => {
    setup();
    await selectRole();
    dropFiles("missions", [new File(["x"], "foo.pdf")]);
    await waitFor(() => expect(rolesApi.createDoc).not.toHaveBeenCalled());
  });

  it("rejects a .md file larger than 1 MiB", async () => {
    setup();
    await selectRole();
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "big.md");
    dropFiles("missions", [big]);
    await waitFor(() => expect(rolesApi.createDoc).not.toHaveBeenCalled());
  });

  it("creates N documents in order when no conflict", async () => {
    vi.mocked(rolesApi.createDoc).mockResolvedValue({ ok: true } as never);
    setup();
    await selectRole();
    dropFiles("competences", [
      new File(["a"], "a.md"),
      new File(["b"], "b.md"),
      new File(["c"], "c.md"),
    ]);
    await waitFor(() => expect(rolesApi.createDoc).toHaveBeenCalledTimes(3));
    expect(rolesApi.createDoc).toHaveBeenNthCalledWith(1, "role-1", {
      section: "competences", name: "a", content_md: "a",
    });
  });

  it("opens conflict dialog when a dropped file matches an existing document name", async () => {
    setup();
    await selectRole();
    dropFiles("missions", [new File(["new"], "existing.md")]);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText(/existing/)).toBeInTheDocument();
  });

  it("replaces via updateDoc when user clicks Replace", async () => {
    vi.mocked(rolesApi.updateDoc).mockResolvedValue({ ok: true } as never);
    setup();
    await selectRole();
    dropFiles("missions", [new File(["new content"], "existing.md")]);
    fireEvent.click(await screen.findByRole("button", { name: /remplacer|replace/i }));
    await waitFor(() => expect(rolesApi.updateDoc).toHaveBeenCalledWith(
      "role-1", "d1", { content_md: "new content" },
    ));
  });
});
```

- [ ] **Step 6.2 : Exécuter, vérifier fail**

Run: `cd frontend && npx vitest run tests/pages/RolesPage.test.tsx`
Expected: FAIL — `section-dropzone-*` introuvable, `handleDropFiles` absent.

- [ ] **Step 6.3 : Modifier `RolesPage.tsx`**

Imports à ajouter en haut :

```tsx
import { toast } from "sonner";
import {
  isMarkdownFile,
  sanitizeDocName,
  findFreeName,
  MAX_FILE_SIZE_BYTES,
} from "@/lib/dropFiles";
import {
  DropConflictDialog,
  type ConflictResolution,
} from "@/components/DropConflictDialog";
```

À l'intérieur du composant, ajouter le state et la fonction `handleDropFiles` :

```tsx
type PendingConflict = {
  file: File;
  content: string;
  existingDocId: string;
  suggestedRename: string;
};

const [conflicts, setConflicts] = useState<PendingConflict[]>([]);
const [bulkAction, setBulkAction] = useState<ConflictResolution["action"] | null>(null);

async function handleDropFiles(section: Section, files: File[]) {
  if (!selectedRoleId || !currentRole) return;

  const existingNames = currentRole.documents
    .filter((d) => d.section === section)
    .map((d) => d.name);
  const existingByName: Record<string, string> = Object.fromEntries(
    currentRole.documents.filter((d) => d.section === section).map((d) => [d.name, d.id]),
  );

  type PreparedItem =
    | { kind: "create"; file: File; name: string; content: string }
    | { kind: "conflict"; conflict: PendingConflict };

  const prepared: PreparedItem[] = [];
  let accumulatedNames = [...existingNames];

  for (const file of files) {
    if (!isMarkdownFile(file)) {
      toast.error(t("roles.drop.error_extension", { name: file.name }));
      continue;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      toast.error(t("roles.drop.error_size", { name: file.name }));
      continue;
    }
    const name = sanitizeDocName(file.name);
    if (!name) {
      toast.error(t("roles.drop.error_name", { name: file.name }));
      continue;
    }
    let content: string;
    try {
      content = await file.text();
      if (content.includes("\uFFFD")) throw new Error("encoding");
    } catch {
      toast.error(t("roles.drop.error_encoding", { name: file.name }));
      continue;
    }

    if (name in existingByName) {
      prepared.push({
        kind: "conflict",
        conflict: {
          file,
          content,
          existingDocId: existingByName[name],
          suggestedRename: findFreeName(name, accumulatedNames),
        },
      });
    } else {
      prepared.push({ kind: "create", file, name, content });
      accumulatedNames.push(name);
    }
  }

  // Exécute tout ce qui n'est pas conflit tout de suite.
  const creates = prepared.filter((p) => p.kind === "create") as Array<Extract<PreparedItem, { kind: "create" }>>;
  let created = 0;
  let failed = 0;
  for (const item of creates) {
    try {
      await rolesApi.createDoc(selectedRoleId, {
        section,
        name: item.name,
        content_md: item.content,
      });
      created += 1;
    } catch {
      failed += 1;
      toast.error(t("roles.drop.error_network", { name: item.file.name }));
    }
  }

  // Empile les conflits ; le dialog traite l'un après l'autre.
  const conflictItems = prepared
    .filter((p) => p.kind === "conflict")
    .map((p) => (p as Extract<PreparedItem, { kind: "conflict" }>).conflict);
  if (conflictItems.length > 0) {
    setConflicts(conflictItems);
    // ref: finalisation via le callback onResolveConflict (ci-dessous).
    // On enregistre créés/échoués pour les ajouter au toast final.
    pendingSummaryRef.current = { section, created, replaced: 0, failed };
  } else {
    emitFinalToast(section, created, 0, failed);
  }
}

const pendingSummaryRef = useRef<{ section: Section; created: number; replaced: number; failed: number } | null>(null);

async function onResolveConflict(resolution: ConflictResolution) {
  const [head, ...rest] = conflicts;
  if (!head || !selectedRoleId) return;
  const summary = pendingSummaryRef.current;
  if (!summary) return;

  if (resolution.action === "replace") {
    try {
      await rolesApi.updateDoc(selectedRoleId, head.existingDocId, { content_md: head.content });
      summary.replaced += 1;
    } catch {
      summary.failed += 1;
      toast.error(t("roles.drop.error_network", { name: head.file.name }));
    }
  } else if (resolution.action === "rename") {
    try {
      await rolesApi.createDoc(selectedRoleId, {
        section: summary.section,
        name: head.suggestedRename,
        content_md: head.content,
      });
      summary.created += 1;
    } catch {
      summary.failed += 1;
      toast.error(t("roles.drop.error_network", { name: head.file.name }));
    }
  } else {
    summary.failed += 1;
  }

  // Applique à tous : consomme le reste automatiquement avec la même action.
  let remaining = rest;
  if (resolution.applyToAll) {
    for (const c of remaining) {
      if (resolution.action === "replace") {
        try {
          await rolesApi.updateDoc(selectedRoleId, c.existingDocId, { content_md: c.content });
          summary.replaced += 1;
        } catch {
          summary.failed += 1;
          toast.error(t("roles.drop.error_network", { name: c.file.name }));
        }
      } else if (resolution.action === "rename") {
        try {
          await rolesApi.createDoc(selectedRoleId, {
            section: summary.section,
            name: c.suggestedRename,
            content_md: c.content,
          });
          summary.created += 1;
        } catch {
          summary.failed += 1;
          toast.error(t("roles.drop.error_network", { name: c.file.name }));
        }
      } else {
        summary.failed += 1;
      }
    }
    remaining = [];
  }

  setConflicts(remaining);
  if (remaining.length === 0) {
    emitFinalToast(summary.section, summary.created, summary.replaced, summary.failed);
    pendingSummaryRef.current = null;
    queryClient.invalidateQueries({ queryKey: ["role", selectedRoleId] });
  }
}

function emitFinalToast(section: Section, created: number, replaced: number, failed: number) {
  if (created === 0 && replaced === 0 && failed === 0) return;
  if (failed === 0 && replaced === 0) {
    toast.success(t("roles.drop.toast_success", { count: created, section }));
  } else if (failed === 0 && created === 0) {
    toast.success(t("roles.drop.toast_replaced", { count: replaced, section }));
  } else if (created === 0 && replaced === 0) {
    toast.error(t("roles.drop.toast_none"));
  } else {
    toast(t("roles.drop.toast_mixed", { created, replaced, failed }));
  }
}
```

Câbler la sidebar :

```tsx
<RoleSidebar
  {...existingProps}
  onFilesDropped={handleDropFiles}
/>
```

Et monter le dialog juste après la sidebar (ou près des autres dialogs du fichier) :

```tsx
<DropConflictDialog
  open={conflicts.length > 0}
  name={conflicts[0]?.file.name ?? ""}
  section={pendingSummaryRef.current?.section ?? ""}
  suggestedRename={conflicts[0]?.suggestedRename ?? ""}
  onOpenChange={(o) => !o && setConflicts([])}
  onResolve={onResolveConflict}
/>
```

Import à ajouter si absent : `import { useRef } from "react";` et `import { useQueryClient } from "@tanstack/react-query";` puis `const queryClient = useQueryClient();`.

- [ ] **Step 6.4 : Re-exécuter les tests**

Run: `cd frontend && npx vitest run tests/pages/RolesPage.test.tsx`
Expected: PASS — 5 tests verts.

- [ ] **Step 6.5 : Commit**

```bash
git add frontend/src/pages/RolesPage.tsx frontend/tests/pages/RolesPage.test.tsx
git commit -m "feat(roles): handleDropFiles — validation, conflits, mutations, toast"
```

---

## Task 7 : Vérifications finales et non-régression

**Files:** (aucun)

- [ ] **Step 7.1 : TypeScript strict sur tout le front**

Run: `cd frontend && npx tsc --noEmit`
Expected: aucune erreur.

- [ ] **Step 7.2 : ESLint**

Run: `cd frontend && npm run lint`
Expected: aucune erreur. (Les warnings liés à des fichiers non modifiés ne comptent pas, ceux introduits par ce chantier doivent être à zéro.)

- [ ] **Step 7.3 : Tous les tests Vitest**

Run: `cd frontend && npm test`
Expected: toutes les suites passent, pas de régression sur les tests préexistants de RolesPage / RoleSidebar / useRoles.

- [ ] **Step 7.4 : Format Prettier**

Run: `cd frontend && npm run format`
Expected: quelques fichiers reformatés, commit intermédiaire uniquement si diff.

```bash
git diff --quiet || git commit -am "chore(roles): prettier format du code drag-drop"
```

- [ ] **Step 7.5 : Commit final de plan (si besoin)**

Tout doit déjà être committé. Vérifier `git status` → working tree clean.

---

## Vérification E2E (manuelle, après deploy LXC 201)

Pas de stack locale (`project_no_local_tests.md`). Après `./scripts/deploy.sh` :

1. Ouvrir `https://admin.agflow.yoops.org/roles`, sélectionner un rôle
2. Drag 1 `.md` depuis Windows → section MISSIONS : doc créé, toast `1 document créé`
3. Drag 3 `.md` simultanés sur COMPETENCES : 3 docs, toast `3 créés`
4. Drag un `.pdf` : toast erreur extension, rien créé
5. Drag un `.md` en conflit : dialog 3 boutons ; tester chaque action
6. Drag 4 fichiers dont 2 conflits + case « Appliquer à tous: Remplacer » : dialog apparaît une seule fois, 4 docs OK
7. F5 : documents persistés côté backend
8. `Esc` pendant drag : highlight retombe, aucun appel réseau

---

## Self-review (effectué)

- **Couverture spec** : intent (T1+T6), drop zone (T5), conflits (T4+T6), extension filter (T1+T6), taille 1 Mio (T1+T6), feedback sobre + toast (T6), échec partiel (T6). ✓
- **Placeholder scan** : aucune occurrence de TBD, TODO, « fill in », « similar to… ». Les valeurs numériques (1 MiB, `-2/-3…`) sont explicites. ✓
- **Type consistency** : `ConflictResolution.action`, `onFilesDropped(section, files)`, `pendingSummaryRef` cohérents entre Task 4, 5, 6. ✓
- **Pas de ref à un symbole indéfini** : `Section`, `SectionSummary`, `DocumentSummary` viennent de `rolesApi.ts` existant. `rolesApi.createDoc/updateDoc` = API en place. ✓
