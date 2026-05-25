// frontend/src/components/projects/__tests__/EnvVarsBanner.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { EnvVarsBanner } from "@/components/projects/EnvVarsBanner";
import type { ProjectEnvVarsCheck } from "@/lib/infraEnvVarsApi";

// Stub i18next : retourne la cle brute avec interpolation simple
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let result = key;
      if (opts) {
        for (const [k, v] of Object.entries(opts)) {
          result = result.replace(`{{${k}}}`, String(v));
        }
      }
      return result;
    },
  }),
}));

const SAMPLE_CHECK: ProjectEnvVarsCheck = {
  project_id: "p1",
  total_missing: 2,
  items: [
    {
      group_script_id: "gs1",
      script_id: "s1",
      script_name: "create-oidc-client",
      group_id: "g1",
      group_name: "primary",
      machine_id: null,
      machine_name: null,
      target_kind: "deployment_host",
      missing: [
        {
          var_name: "KC_ADMIN_PASSWORD",
          kind: "machine_not_found",
          ref: "${env-machine://ghost:KC_ADMIN_PASSWORD}",
          detail: "machine 'ghost' inconnue",
        },
        {
          var_name: "REALM",
          kind: "value_empty",
          ref: "",
          detail: "valeur vide pour 'REALM'",
        },
      ],
    },
  ],
};

describe("EnvVarsBanner", () => {
  it("renders nothing when total_missing is 0", () => {
    const { container } = render(
      <EnvVarsBanner check={{ project_id: "p1", total_missing: 0, items: [] }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders one reason per missing variable with i18n key", () => {
    render(<EnvVarsBanner check={SAMPLE_CHECK} />);

    // Banner headline avec le count interpole
    expect(
      screen.getByText(/projects\.env_vars_missing_banner/),
    ).toBeInTheDocument();

    // Script + group identifiers
    expect(screen.getByText("create-oidc-client")).toBeInTheDocument();
    expect(screen.getByText("primary")).toBeInTheDocument();

    // Variable names
    expect(screen.getByText("KC_ADMIN_PASSWORD")).toBeInTheDocument();
    expect(screen.getByText("REALM")).toBeInTheDocument();

    // Reason keys with interpolated detail
    expect(
      screen.getByText(/projects\.env_vars_reason\.machine_not_found/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/projects\.env_vars_reason\.value_empty/),
    ).toBeInTheDocument();
  });

  it("renders all items when multiple group_scripts have missing vars", () => {
    const multiCheck: ProjectEnvVarsCheck = {
      project_id: "p1",
      total_missing: 3,
      items: [
        {
          group_script_id: "gs1",
          script_id: "s1",
          script_name: "setup-keycloak",
          group_id: "g1",
          group_name: "auth",
          machine_id: "m1",
          machine_name: "kc-host",
          target_kind: "fixed_machine",
          missing: [
            {
              var_name: "KC_SECRET",
              kind: "platform_secret_missing",
              ref: "${vault://api:KC_SECRET}",
              detail: "secret 'KC_SECRET' introuvable",
            },
          ],
        },
        {
          group_script_id: "gs2",
          script_id: "s2",
          script_name: "init-db",
          group_id: "g2",
          group_name: "data",
          machine_id: null,
          machine_name: null,
          target_kind: "deployment_host",
          missing: [
            {
              var_name: "DB_PASSWORD",
              kind: "var_not_in_env",
              ref: "${DB_PASSWORD}",
              detail: "variable 'DB_PASSWORD' introuvable dans le .env",
            },
            {
              var_name: "DB_USER",
              kind: "value_empty",
              ref: "",
              detail: "valeur vide pour 'DB_USER'",
            },
          ],
        },
      ],
    };

    render(<EnvVarsBanner check={multiCheck} />);
    expect(screen.getByText("setup-keycloak")).toBeInTheDocument();
    expect(screen.getByText("init-db")).toBeInTheDocument();
    expect(screen.getByText("KC_SECRET")).toBeInTheDocument();
    expect(screen.getByText("DB_PASSWORD")).toBeInTheDocument();
    expect(screen.getByText("DB_USER")).toBeInTheDocument();
  });
});
