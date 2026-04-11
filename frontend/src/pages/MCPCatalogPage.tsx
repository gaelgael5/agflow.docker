import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDiscoveryServices, useMCPCatalog } from "@/hooks/useCatalogs";
import { SearchModal } from "@/components/SearchModal";
import { discoveryApi, type MCPSearchItem } from "@/lib/catalogsApi";

export function MCPCatalogPage() {
  const { t } = useTranslation();
  const { services } = useDiscoveryServices();
  const { mcps, isLoading, installMutation, deleteMutation } = useMCPCatalog();
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(
    null,
  );

  // Group by repo
  const grouped = (mcps ?? []).reduce<Record<string, typeof mcps>>((acc, m) => {
    const key = m.repo || "(other)";
    if (!acc[key]) acc[key] = [];
    acc[key]!.push(m);
    return acc;
  }, {});

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(t("mcp_catalog.confirm_delete", { name }))) return;
    await deleteMutation.mutateAsync(id);
  }

  async function handleSearch(query: string, semantic: boolean) {
    if (!selectedServiceId) return [];
    return discoveryApi.searchMcp(selectedServiceId, query, semantic);
  }

  async function handleInstall(item: MCPSearchItem) {
    if (!selectedServiceId) return;
    await installMutation.mutateAsync({
      discoveryServiceId: selectedServiceId,
      packageId: item.package_id,
    });
    setSearchOpen(false);
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  const hasServices = (services ?? []).length > 0;

  return (
    <div style={{ padding: "2rem", maxWidth: 1200 }}>
      <h1>{t("mcp_catalog.page_title")}</h1>
      <p>{t("mcp_catalog.page_subtitle")}</p>

      {!hasServices ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("mcp_catalog.no_services")}
        </p>
      ) : (
        <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
          <label>
            {t("mcp_catalog.select_service")}:{" "}
            <select
              value={selectedServiceId ?? ""}
              onChange={(e) => setSelectedServiceId(e.target.value || null)}
            >
              <option value="">—</option>
              {services?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            disabled={!selectedServiceId}
          >
            {t("mcp_catalog.search_button")}
          </button>
        </div>
      )}

      {(mcps ?? []).length === 0 ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("mcp_catalog.no_mcps")}
        </p>
      ) : (
        Object.entries(grouped).map(([repo, list]) => (
          <div key={repo} style={{ marginBottom: "1.5rem" }}>
            <h3 style={{ borderBottom: "1px solid #ccc", paddingBottom: "4px" }}>
              {repo} ({list?.length ?? 0})
            </h3>
            <ul style={{ listStyle: "none", padding: 0 }}>
              {list?.map((m) => (
                <li
                  key={m.id}
                  style={{
                    padding: "0.5rem",
                    borderBottom: "1px solid #eee",
                    display: "flex",
                    alignItems: "center",
                    gap: "1rem",
                  }}
                >
                  <div style={{ flex: 1 }}>
                    <strong>{m.name}</strong>{" "}
                    <code style={{ fontSize: "11px", color: "#666" }}>
                      {m.package_id}
                    </code>
                    <div style={{ fontSize: "12px", color: "#666" }}>
                      <span
                        style={{
                          background: "#e0e7ff",
                          padding: "1px 6px",
                          borderRadius: "3px",
                          marginRight: "0.5rem",
                        }}
                      >
                        {m.transport}
                      </span>
                      {m.short_description}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDelete(m.id, m.name)}
                    style={{ color: "red" }}
                  >
                    {t("mcp_catalog.delete_button")}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}

      {searchOpen && selectedServiceId && (
        <SearchModal<MCPSearchItem>
          title={t("mcp_catalog.page_title")}
          showSemantic
          onSearch={handleSearch}
          onAdd={handleInstall}
          renderItem={(item) => (
            <div>
              <strong>{item.name}</strong>{" "}
              <code style={{ fontSize: "11px" }}>{item.package_id}</code>
              <div style={{ fontSize: "12px", color: "#666" }}>
                <span
                  style={{
                    background: "#e0e7ff",
                    padding: "1px 6px",
                    borderRadius: "3px",
                    marginRight: "0.5rem",
                  }}
                >
                  {item.transport}
                </span>
                {item.short_description}
              </div>
            </div>
          )}
          onClose={() => setSearchOpen(false)}
        />
      )}
    </div>
  );
}
