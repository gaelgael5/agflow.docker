import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface Props<T> {
  title: string;
  showSemantic?: boolean;
  onSearch: (query: string, semantic: boolean) => Promise<T[]>;
  onAdd: (item: T) => Promise<void>;
  renderItem: (item: T) => ReactNode;
  onClose: () => void;
}

export function SearchModal<T>({
  title,
  showSemantic = false,
  onSearch,
  onAdd,
  renderItem,
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
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "white",
          padding: "1.5rem",
          borderRadius: "8px",
          width: "min(780px, 92%)",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <h2 style={{ margin: 0 }}>
          {t("search_modal.title", { title })}
        </h2>

        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginTop: "1rem",
            alignItems: "center",
          }}
        >
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("search_modal.placeholder")}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSearch();
            }}
            style={{ flex: 1, padding: "6px" }}
          />
          {showSemantic && (
            <label style={{ fontSize: "13px", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={semantic}
                onChange={(e) => setSemantic(e.target.checked)}
              />{" "}
              {t("search_modal.semantic_label")}
            </label>
          )}
          <button type="button" onClick={handleSearch} disabled={loading}>
            {loading
              ? t("search_modal.loading")
              : t("search_modal.search_button")}
          </button>
        </div>

        {error && (
          <p role="alert" style={{ color: "red", marginTop: "0.5rem" }}>
            {error}
          </p>
        )}

        <div
          style={{
            flex: 1,
            overflow: "auto",
            marginTop: "1rem",
            borderTop: "1px solid #eee",
          }}
        >
          {results === null ? null : results.length === 0 ? (
            <p style={{ color: "#999", fontStyle: "italic" }}>
              {t("search_modal.no_results")}
            </p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0 }}>
              {results.map((item, idx) => (
                <li
                  key={idx}
                  style={{
                    borderBottom: "1px solid #eee",
                    padding: "0.75rem",
                    display: "flex",
                    gap: "0.75rem",
                  }}
                >
                  <div style={{ flex: 1 }}>{renderItem(item)}</div>
                  <button type="button" onClick={() => handleAdd(item)}>
                    {t("search_modal.add_button")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          style={{ marginTop: "1rem", alignSelf: "flex-end" }}
        >
          {t("search_modal.close")}
        </button>
      </div>
    </div>
  );
}
