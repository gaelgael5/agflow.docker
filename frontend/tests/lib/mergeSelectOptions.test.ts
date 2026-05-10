import { describe, it, expect } from "vitest";
import { mergeSelectOptions } from "@/lib/mergeSelectOptions";

const opt = (value: string, label = value) => ({ value, label });

// Cas 1 : options statiques seules — ordre manifest préservé
describe("options statiques seules", () => {
  it("préserve l'ordre du manifest", () => {
    const result = mergeSelectOptions(
      [opt("bare", "VM nue"), opt("docker", "VM + Docker"), opt("swarm", "VM swarm-ready"), opt("init-swarm", "VM + Docker + init"), opt("join-swarm", "VM + Docker + join")],
      [],
    );
    expect(result.map((o) => o.value)).toEqual(["bare", "docker", "swarm", "init-swarm", "join-swarm"]);
  });

  it("conserve les labels du manifest", () => {
    const result = mergeSelectOptions([opt("auto", "auto (sélection automatique)")], []);
    expect(result[0]).toEqual({ value: "auto", label: "auto (sélection automatique)" });
  });
});

// Cas 2 : option_script seul — trié alphabétiquement
describe("option_script seul, pas d'options statiques", () => {
  it("trie les valeurs dynamiques alphabétiquement", () => {
    const result = mergeSelectOptions([], ["local-lvm", "extended-lvm", "local"]);
    expect(result.map((o) => o.value)).toEqual(["extended-lvm", "local", "local-lvm"]);
  });

  it("value == label pour les entrées dynamiques", () => {
    const result = mergeSelectOptions([], ["zpool", "apool"]);
    expect(result).toEqual([opt("apool"), opt("zpool")]);
  });
});

// Cas 3 : les deux présents — STATIC puis DYNAMIC_SORTED, dédup
describe("mix statique + dynamique", () => {
  it("applique l'exemple STORAGE du contrat", () => {
    const result = mergeSelectOptions(
      [opt("auto", "auto (sélection automatique)")],
      ["local-lvm", "extended-lvm", "local", "auto"],
    );
    expect(result.map((o) => o.value)).toEqual(["auto", "extended-lvm", "local", "local-lvm"]);
    expect(result[0]!.label).toBe("auto (sélection automatique)");
  });
});

// Cas 4 : option_script échoue → fallback STATIC_LIST (dynamicValues vide)
describe("option_script échoue (fallback)", () => {
  it("retourne uniquement la liste statique quand dynamicValues est vide", () => {
    const result = mergeSelectOptions([opt("auto", "auto (sélection auto)")], []);
    expect(result).toEqual([{ value: "auto", label: "auto (sélection auto)" }]);
  });
});

// Cas 5 : option_script renvoie 0 ligne
describe("option_script renvoie 0 ligne", () => {
  it("retourne la liste statique intacte", () => {
    const result = mergeSelectOptions([opt("local"), opt("ceph")], []);
    expect(result.map((o) => o.value)).toEqual(["local", "ceph"]);
  });
});

// Cas 6 : doublon entre options et script — position du STATIC préservée
describe("doublon entre options statiques et script", () => {
  it("la valeur statique garde sa position, le doublon dynamique est éliminé", () => {
    const result = mergeSelectOptions(
      [opt("a", "A-label"), opt("b", "B-label")],
      ["c", "a", "d"],
    );
    expect(result.map((o) => o.value)).toEqual(["a", "b", "c", "d"]);
    expect(result[0]!.label).toBe("A-label");
  });
});

// Cas 7 : default présent dans la liste → déplacé en tête
describe("default présent dans la liste", () => {
  it("déplace la valeur default en tête", () => {
    const result = mergeSelectOptions(
      [opt("bare"), opt("docker"), opt("init-swarm")],
      [],
      "init-swarm",
    );
    expect(result[0]!.value).toBe("init-swarm");
    expect(result.map((o) => o.value)).toContain("bare");
    expect(result.map((o) => o.value)).toContain("docker");
  });

  it("ne duplique pas le default déjà en tête", () => {
    const result = mergeSelectOptions([opt("auto"), opt("local")], [], "auto");
    expect(result.filter((o) => o.value === "auto")).toHaveLength(1);
    expect(result[0]!.value).toBe("auto");
  });
});

// Cas 8 : default absent de la liste → injecté en tête
describe("default absent de la liste", () => {
  it("injecte le default en tête", () => {
    const result = mergeSelectOptions([opt("local")], [], "missing-default");
    expect(result[0]!.value).toBe("missing-default");
    expect(result).toHaveLength(2);
  });
});

// Cas 9 : default non défini → pas de réordonnancement
describe("default non défini", () => {
  it("ne modifie pas l'ordre", () => {
    const result = mergeSelectOptions([opt("b"), opt("a")], []);
    expect(result.map((o) => o.value)).toEqual(["b", "a"]);
  });
});

// Cas 10 : select sans options ni option_script → liste vide (erreur de validation amont)
describe("select sans options ni option_script", () => {
  it("retourne une liste vide", () => {
    const result = mergeSelectOptions([], []);
    expect(result).toEqual([]);
  });
});

// Cas 11 : SSH down → dynamicValues = [] (même comportement que cas 4/5)
describe("hôte SSH inaccessible", () => {
  it("retombe sur les options statiques (dynamicValues vide)", () => {
    const result = mergeSelectOptions(
      [opt("auto", "auto (sélection auto)"), opt("local")],
      [],
    );
    expect(result.map((o) => o.value)).toEqual(["auto", "local"]);
  });
});
