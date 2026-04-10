import { useTranslation } from "react-i18next";
import { useBuild } from "@/hooks/useBuild";

interface Props {
  dockerfileId: string;
  dockerfileName: string;
  buildId: string;
  onClose: () => void;
}

export function BuildModal({
  dockerfileId,
  dockerfileName,
  buildId,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const build = useBuild(dockerfileId, buildId);

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
          width: "min(900px, 90%)",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <h2 style={{ margin: 0 }}>
          {t("dockerfiles.build_modal.title", { dockerfile: dockerfileName })}
        </h2>
        {build && (
          <>
            <p style={{ fontSize: "13px", color: "#555" }}>
              <strong>{t("dockerfiles.build_modal.image_tag")}:</strong>{" "}
              <code>{build.image_tag}</code>
            </p>
            <p>
              <strong>Status:</strong>{" "}
              {build.status === "success"
                ? `✅ ${t("dockerfiles.build_modal.success")}`
                : build.status === "failed"
                  ? `❌ ${t("dockerfiles.build_modal.failed")}`
                  : `🔵 ${t("dockerfiles.build_modal.running")}`}
            </p>
            <strong>{t("dockerfiles.build_modal.logs")}</strong>
            <pre
              style={{
                flex: 1,
                overflow: "auto",
                background: "#111",
                color: "#0f0",
                padding: "0.75rem",
                fontSize: "12px",
                margin: "0.5rem 0",
                whiteSpace: "pre-wrap",
              }}
            >
              {build.logs || "..."}
            </pre>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          style={{ alignSelf: "flex-end" }}
        >
          {t("dockerfiles.build_modal.close")}
        </button>
      </div>
    </div>
  );
}
