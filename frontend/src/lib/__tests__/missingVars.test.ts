// frontend/src/lib/__tests__/missingVars.test.ts
import { describe, it, expect } from "vitest";
import { isMissing, getOrigin, type VarSources } from "../missingVars";

const sources: VarSources = {
  globalVarNames: new Set(["GLOBAL_TOKEN"]),
  groupVarNames: new Set(["INTERNAL_URL", "KC_ADMIN_PASSWORD"]),
  beforeOutputNames: new Set(["CLIENT_ID"]),
};

describe("isMissing", () => {
  it("pas manquante si varName dans globalVarNames", () => {
    expect(isMissing("GLOBAL_TOKEN", "", sources)).toBe(false);
  });

  it("pas manquante si varName dans groupVarNames", () => {
    expect(isMissing("INTERNAL_URL", "", sources)).toBe(false);
  });

  it("pas manquante si varName dans beforeOutputNames", () => {
    expect(isMissing("CLIENT_ID", "", sources)).toBe(false);
  });

  it("manquante si valeur vide et varName absent de toutes les sources", () => {
    expect(isMissing("UNKNOWN_VAR", "", sources)).toBe(true);
  });

  it("manquante si valeur vide et undefined", () => {
    expect(isMissing("UNKNOWN_VAR", undefined, sources)).toBe(true);
  });

  it("pas manquante si valeur littérale (pas de ${})", () => {
    expect(isMissing("UNKNOWN_VAR", "http://localhost:3000", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via groupVarNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${INTERNAL_URL}", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via globalVarNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${GLOBAL_TOKEN}", sources)).toBe(false);
  });

  it("pas manquante si ${REF} résolvable via beforeOutputNames", () => {
    expect(isMissing("UNKNOWN_VAR", "${CLIENT_ID}", sources)).toBe(false);
  });

  it("manquante si ${REF} non résolvable", () => {
    expect(isMissing("UNKNOWN_VAR", "${MYSTERY_VAR}", sources)).toBe(true);
  });
});

describe("getOrigin", () => {
  it("global si varName dans globalVarNames", () => {
    expect(getOrigin("GLOBAL_TOKEN", "", sources)).toBe("global");
  });

  it("group si varName dans groupVarNames", () => {
    expect(getOrigin("INTERNAL_URL", "http://x", sources)).toBe("group");
  });

  it("before_script si varName dans beforeOutputNames", () => {
    expect(getOrigin("CLIENT_ID", "", sources)).toBe("before_script");
  });

  it("manual si valeur littérale et varName absent", () => {
    expect(getOrigin("UNKNOWN", "http://localhost", sources)).toBe("manual");
  });

  it("missing si valeur vide et varName absent", () => {
    expect(getOrigin("UNKNOWN", "", sources)).toBe("missing");
  });

  it("group si ${REF} pointe vers groupVarNames", () => {
    expect(getOrigin("UNKNOWN", "${INTERNAL_URL}", sources)).toBe("group");
  });

  it("global si ${REF} pointe vers globalVarNames", () => {
    expect(getOrigin("UNKNOWN", "${GLOBAL_TOKEN}", sources)).toBe("global");
  });

  it("missing si ${REF} non résolvable", () => {
    expect(getOrigin("UNKNOWN", "${NOWHERE}", sources)).toBe("missing");
  });
});
