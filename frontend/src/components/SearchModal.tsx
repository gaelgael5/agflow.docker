import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Search } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

interface Props<T> {
  title: string;
  showSemantic?: boolean;
  onSearch: (query: string, semantic: boolean) => Promise<T[]>;
  onAdd: (item: T) => Promise<void>;
  renderItem: (item: T) => ReactNode;
  groupBy?: (item: T) => string;
  onClose: () => void;
}

export function SearchModal<T>({
  title,
  showSemantic = false,
  onSearch,
  onAdd,
  renderItem,
  groupBy,
  onClose,
}: Props<T>) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [semantic, setSemantic] = useState(false);
  const [results, setResults] = useState<T[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    setLoading(true);
    setError(null);
    try {
      const items = await onSearch(query, semantic);
      setResults(items);
    } catch {
      setError(t("search_modal.error"));
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  async function handleAdd(item: T) {
    try {
      await onAdd(item);
    } catch {
      setError(t("search_modal.error"));
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("search_modal.title", { title })}</DialogTitle>
          <DialogDescription className="sr-only">
            {t("search_modal.placeholder")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("search_modal.placeholder")}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
              className="pl-9"
            />
          </div>
          {showSemantic && (
            <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground whitespace-nowrap cursor-pointer select-none">
              <input
                type="checkbox"
                checked={semantic}
                onChange={(e) => setSemantic(e.target.checked)}
                className="h-3.5 w-3.5 rounded border border-input accent-primary"
              />
              {t("search_modal.semantic_label")}
            </label>
          )}
          <Button onClick={handleSearch} disabled={loading}>
            {loading
              ? t("search_modal.loading")
              : t("search_modal.search_button")}
          </Button>
        </div>

        {error && (
          <p role="alert" className="text-destructive text-[12px]">
            {error}
          </p>
        )}

        <div className="flex-1 overflow-y-auto -mx-6 px-6 border-t pt-2">
          {loading && results === null ? (
            <div className="space-y-2 py-3">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : results === null ? (
            <p className="text-muted-foreground text-[13px] italic py-3">
              {t("search_modal.hint")}
            </p>
          ) : results.length === 0 ? (
            <p className="text-muted-foreground text-[13px] italic py-3">
              {t("search_modal.no_results")}
            </p>
          ) : groupBy ? (
            (() => {
              const groups: Record<string, T[]> = {};
              for (const item of results) {
                const key = groupBy(item) || "—";
                (groups[key] ??= []).push(item);
              }
              return (
                <div className="space-y-3 py-2">
                  {Object.entries(groups).map(([group, items]) => (
                    <div key={group}>
                      <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider px-1 mb-1">
                        {group} ({items.length})
                      </div>
                      <ul className="divide-y">
                        {items.map((item, idx) => (
                          <li key={idx} className="flex items-center gap-3 py-2">
                            <div className="flex-1 min-w-0">{renderItem(item)}</div>
                            <Button variant="outline" size="sm" onClick={() => handleAdd(item)}>
                              <Plus className="w-3.5 h-3.5" />
                              {t("search_modal.add_button")}
                            </Button>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              );
            })()
          ) : (
            <ul className="divide-y">
              {results.map((item, idx) => (
                <li
                  key={idx}
                  className="flex items-center gap-3 py-3"
                >
                  <div className="flex-1 min-w-0">{renderItem(item)}</div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleAdd(item)}
                  >
                    <Plus className="w-3.5 h-3.5" />
                    {t("search_modal.add_button")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
