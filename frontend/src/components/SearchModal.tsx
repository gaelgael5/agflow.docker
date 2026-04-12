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
  /** Kept for API compat — no-op since real registry doesn't support it. */
  showSemantic?: boolean;
  onSearch: (query: string, semantic: boolean) => Promise<T[]>;
  onAdd: (item: T) => Promise<void>;
  renderItem: (item: T) => ReactNode;
  onClose: () => void;
}

export function SearchModal<T>({
  title,
  onSearch,
  onAdd,
  renderItem,
  onClose,
}: Props<T>) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<T[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSearch() {
    setLoading(true);
    setError(null);
    try {
      const items = await onSearch(query, false);
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
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
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
