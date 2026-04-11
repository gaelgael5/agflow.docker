import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useDiscoveryServices, useSkillsCatalog } from "@/hooks/useCatalogs";
import { SearchModal } from "@/components/SearchModal";
import { discoveryApi, type SkillSearchItem } from "@/lib/catalogsApi";

export function SkillsCatalogPage() {
  const { t } = useTranslation();
  const { services } = useDiscoveryServices();
  const { skills, isLoading, installMutation, deleteMutation } =
    useSkillsCatalog();
  const [searchOpen, setSearchOpen] = useState(false);
  const [selectedServiceId, setSelectedServiceId] = useState<string | null>(
    null,
  );

  async function handleDelete(id: string, name: string) {
    if (!window.confirm(t("skills_catalog.confirm_delete", { name }))) return;
    await deleteMutation.mutateAsync(id);
  }

  async function handleSearch(query: string) {
    if (!selectedServiceId) return [];
    return discoveryApi.searchSkills(selectedServiceId, query);
  }

  async function handleInstall(item: SkillSearchItem) {
    if (!selectedServiceId) return;
    await installMutation.mutateAsync({
      discoveryServiceId: selectedServiceId,
      skillId: item.skill_id,
    });
    setSearchOpen(false);
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  const hasServices = (services ?? []).length > 0;

  return (
    <div style={{ padding: "2rem", maxWidth: 1200 }}>
      <h1>{t("skills_catalog.page_title")}</h1>
      <p>{t("skills_catalog.page_subtitle")}</p>

      {!hasServices ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("skills_catalog.no_services")}
        </p>
      ) : (
        <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
          <label>
            {t("skills_catalog.select_service")}:{" "}
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
            {t("skills_catalog.search_button")}
          </button>
        </div>
      )}

      {(skills ?? []).length === 0 ? (
        <p style={{ color: "#999", fontStyle: "italic" }}>
          {t("skills_catalog.no_skills")}
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th>{t("skills_catalog.col_name")}</th>
              <th>{t("skills_catalog.col_id")}</th>
              <th>{t("skills_catalog.col_description")}</th>
              <th>{t("skills_catalog.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {skills?.map((s) => (
              <tr key={s.id} style={{ borderBottom: "1px solid #eee" }}>
                <td>
                  <strong>{s.name}</strong>
                </td>
                <td>
                  <code>{s.skill_id}</code>
                </td>
                <td>{s.description}</td>
                <td>
                  <button
                    type="button"
                    onClick={() => handleDelete(s.id, s.name)}
                    style={{ color: "red" }}
                  >
                    {t("skills_catalog.delete_button")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {searchOpen && selectedServiceId && (
        <SearchModal<SkillSearchItem>
          title={t("skills_catalog.page_title")}
          onSearch={handleSearch}
          onAdd={handleInstall}
          renderItem={(item) => (
            <div>
              <strong>{item.name}</strong>{" "}
              <code style={{ fontSize: "11px" }}>{item.skill_id}</code>
              <div style={{ fontSize: "12px", color: "#666" }}>
                {item.description}
              </div>
            </div>
          )}
          onClose={() => setSearchOpen(false)}
        />
      )}
    </div>
  );
}
