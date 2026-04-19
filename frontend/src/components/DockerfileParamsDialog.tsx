import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  dockerfilesApi,
  type FileSummary,
  type MountCheckResult,
} from "@/lib/dockerfilesApi";

interface KVEntry {
  key: string;
  value: string;
}

interface MountEntry {
  source: string;
  target: string;
  readonly: boolean;
}

interface ContainerState {
  Name: string;
  Image: string;
}

interface NetworkState {
  Mode: string;
}

interface RuntimeState {
  Init: boolean;
  StopSignal: string;
  StopTimeout: number;
  WorkingDir: string;
}

interface ResourcesState {
  Memory: string;
  Cpus: string;
}

interface ExcludedState {
  environments: string[];
  mounts: string[];
  params: string[];
}

interface ParamsState {
  slug: string;
  container: ContainerState;
  network: NetworkState;
  runtime: RuntimeState;
  resources: ResourcesState;
  environments: KVEntry[];
  mounts: MountEntry[];
  params: KVEntry[];
  excluded: ExcludedState;
  testOverrides: KVEntry[];
  /** Preserve unknown top-level keys (Target, Generation, etc.) */
  _extra: Record<string, unknown>;
}

// Environment variable names — POSIX rule: letter or underscore followed
// by letters / digits / underscores. No "$", no dashes, no spaces.
const ENV_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

function validateEnvKey(key: string): string | null {
  if (!key) return null;
  if (!ENV_KEY_RE.test(key)) {
    return `"${key}" n'est pas un nom de variable valide`;
  }
  return null;
}

function mountMissingExplanation(
  resolvedPath: string,
  autoPrefixed: boolean,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  const tail = resolvedPath.split("/").pop() ?? "";
  const looksLikeFile = tail.includes(".");
  if (autoPrefixed && !looksLikeFile) {
    return t("dockerfiles.params.mount_missing_dir_autofix");
  }
  if (autoPrefixed && looksLikeFile) {
    return t("dockerfiles.params.mount_missing_file_autoprefix", {
      path: resolvedPath,
    });
  }
  return t("dockerfiles.params.mount_missing_absolute", {
    path: resolvedPath,
  });
}

const BUILTIN_NETWORK_MODES = ["bridge", "host", "none"] as const;
type NetworkType = (typeof BUILTIN_NETWORK_MODES)[number] | "custom";
const MEMORY_UNITS = ["m", "g"] as const;
type MemoryUnit = (typeof MEMORY_UNITS)[number];
const STOP_SIGNALS = ["SIGTERM", "SIGINT", "SIGQUIT", "SIGKILL"] as const;

function deriveNetworkType(mode: string): NetworkType {
  return (BUILTIN_NETWORK_MODES as readonly string[]).includes(mode)
    ? (mode as NetworkType)
    : "custom";
}

function parseMemory(raw: string): { numeric: string; unit: MemoryUnit } {
  const match = raw.trim().match(/^(\d+(?:\.\d+)?)\s*([mg])$/i);
  if (!match) return { numeric: "", unit: "g" };
  return {
    numeric: match[1] ?? "",
    unit: (match[2]?.toLowerCase() ?? "g") as MemoryUnit,
  };
}

function buildMemory(numeric: string, unit: MemoryUnit): string {
  const n = numeric.trim();
  if (!n) return "";
  return `${n}${unit}`;
}

// ─────────────────────────────────────────────────────────────
// Template resolver — recursively substitutes {KEY} placeholders
// using Params (user-defined) + systemVars (slug, etc.). ${VAR}
// shell templating is NEVER touched.
// ─────────────────────────────────────────────────────────────
function resolveTemplates(
  input: string,
  vars: Record<string, string>,
  maxIter = 16,
): string {
  if (!input) return input;
  let current = input;
  for (let i = 0; i < maxIter; i++) {
    const next = current.replace(/\{(\w+)\}/g, (match, key: string) =>
      key in vars ? vars[key]! : match,
    );
    if (next === current) return next;
    current = next;
  }
  return current;
}

// ─────────────────────────────────────────────────────────────
// docker run command builder — derives a live bash preview from
// the current state. {id} and {hash} are left literal so the user
// understands they are resolved by the orchestrator at launch.
// ─────────────────────────────────────────────────────────────
function buildDockerRunCommand(state: ParamsState, applyExclusions: boolean): string {
  const excludedEnvs = applyExclusions ? new Set(state.excluded.environments) : new Set<string>();
  const excludedMounts = applyExclusions ? new Set(state.excluded.mounts) : new Set<string>();
  const excludedParams = applyExclusions ? new Set(state.excluded.params) : new Set<string>();

  const filteredParams = state.params.filter((p) => !excludedParams.has(p.key));
  const vars: Record<string, string> = {
    ...entriesToRecord(filteredParams),
    slug: state.slug,
  };
  const resolve = (s: string) => resolveTemplates(s, vars);

  const lines: string[] = ["docker run -it --rm"];

  const name = resolve(state.container.Name);
  if (name) lines.push(`--name ${name}`);

  if (state.network.Mode) {
    lines.push(`--network ${state.network.Mode}`);
  }
  if (state.runtime.Init) lines.push("--init");
  if (state.runtime.StopSignal) {
    lines.push(`--stop-signal ${state.runtime.StopSignal}`);
  }
  if (
    typeof state.runtime.StopTimeout === "number" &&
    !Number.isNaN(state.runtime.StopTimeout)
  ) {
    lines.push(`--stop-timeout ${state.runtime.StopTimeout}`);
  }
  if (state.runtime.WorkingDir) {
    lines.push(`-w ${state.runtime.WorkingDir}`);
  }
  const memNumeric = parseFloat(parseMemory(state.resources.Memory).numeric);
  if (Number.isFinite(memNumeric) && memNumeric > 0) {
    lines.push(`--memory ${state.resources.Memory}`);
  }
  const cpusNumeric = parseFloat(state.resources.Cpus);
  if (Number.isFinite(cpusNumeric) && cpusNumeric > 0) {
    lines.push(`--cpus ${state.resources.Cpus}`);
  }

  for (const env of state.environments) {
    const key = env.key.trim();
    if (!key || excludedEnvs.has(key)) continue;
    const value = resolve(env.value);
    lines.push(`-e ${key}="${value}"`);
  }

  if (applyExclusions) {
    for (const to of state.testOverrides) {
      const key = to.key.trim();
      if (!key) continue;
      lines.push(`-e ${key}="${to.value}"`);
    }
  }

  for (const mount of state.mounts) {
    const source = mount.source.trim();
    const target = mount.target.trim();
    if (!source || !target || excludedMounts.has(target)) continue;
    const resolvedSource = resolve(source);
    const ro = mount.readonly ? ":ro" : "";
    lines.push(`-v "${resolvedSource}:${target}${ro}"`);
  }

  const image = resolve(state.container.Image);
  lines.push(image || `agflow-${state.slug}:{hash}`);

  return lines.join(" \\\n    ");
}

// ─────────────────────────────────────────────────────────────
// Tiny bash highlighter — regex-based, returns token nodes for
// React rendering. Avoids pulling in react-syntax-highlighter.
// ─────────────────────────────────────────────────────────────
interface BashToken {
  text: string;
  cls: string;
}

const BASH_TOKEN_RE =
  /("(?:\\.|[^"\\])*")|('(?:\\.|[^'\\])*')|(\\$)|(--?[a-zA-Z][\w-]*)|(\$\{[^}]*\}|\$\w+)|(\s+)|([^\s"'$\\]+)|(\\)|([\s\S])/g;

function highlightBash(source: string): BashToken[] {
  const out: BashToken[] = [];
  let isStartOfLogicalLine = true;
  for (const m of source.matchAll(BASH_TOKEN_RE)) {
    const [
      match,
      dq,
      sq,
      trailingBackslash,
      flag,
      shellVar,
      ws,
      word,
      loneBackslash,
    ] = m;
    if (dq !== undefined) {
      out.push({ text: dq, cls: "text-amber-700 dark:text-amber-300" });
      isStartOfLogicalLine = false;
    } else if (sq !== undefined) {
      out.push({ text: sq, cls: "text-amber-700 dark:text-amber-300" });
      isStartOfLogicalLine = false;
    } else if (trailingBackslash !== undefined) {
      out.push({ text: trailingBackslash, cls: "text-zinc-500" });
    } else if (flag !== undefined) {
      out.push({ text: flag, cls: "text-cyan-700 dark:text-cyan-300" });
      isStartOfLogicalLine = false;
    } else if (shellVar !== undefined) {
      out.push({ text: shellVar, cls: "text-violet-600 dark:text-violet-300" });
      isStartOfLogicalLine = false;
    } else if (ws !== undefined) {
      out.push({ text: ws, cls: "" });
      if (ws.includes("\n")) isStartOfLogicalLine = true;
    } else if (word !== undefined) {
      const isCommand = isStartOfLogicalLine && /^[a-zA-Z]/.test(word);
      out.push({
        text: word,
        cls: isCommand ? "text-emerald-700 dark:text-emerald-300 font-semibold" : "text-zinc-800 dark:text-zinc-100",
      });
      isStartOfLogicalLine = false;
    } else if (loneBackslash !== undefined) {
      out.push({ text: loneBackslash, cls: "text-zinc-500" });
    } else if (match) {
      out.push({ text: match, cls: "" });
    }
  }
  return out;
}

const DEFAULT_STATE = (slug: string): ParamsState => ({
  slug,
  container: {
    Name: "agent-{slug}-{id}",
    Image: "agflow-{slug}:{hash}",
  },
  network: { Mode: "bridge" },
  runtime: {
    Init: true,
    StopSignal: "SIGTERM",
    StopTimeout: 30,
    WorkingDir: "/app",
  },
  resources: { Memory: "2g", Cpus: "1.5" },
  environments: [],
  mounts: [],
  params: [],
  excluded: { environments: [], mounts: [], params: [] },
  testOverrides: [],
  _extra: {},
});

function substituteSlug(template: string, slug: string): string {
  return template.replace(/\{slug\}/g, slug);
}

function recordToEntries(obj: Record<string, unknown> | undefined): KVEntry[] {
  if (!obj || typeof obj !== "object") return [];
  return Object.entries(obj).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value : JSON.stringify(value),
  }));
}

function entriesToRecord(entries: KVEntry[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const e of entries) {
    const k = e.key.trim();
    if (k) out[k] = e.value;
  }
  return out;
}

interface Parsed {
  state: ParamsState;
  parseError: string | null;
}

function parseContent(content: string, slug: string): Parsed {
  const fallback = DEFAULT_STATE(slug);
  if (!content.trim()) return { state: fallback, parseError: null };
  let raw: unknown;
  try {
    raw = JSON.parse(content);
  } catch {
    return { state: fallback, parseError: "invalid_json" };
  }
  if (!raw || typeof raw !== "object") {
    return { state: fallback, parseError: "invalid_shape" };
  }
  const root = raw as Record<string, unknown>;
  const docker = (root.docker ?? {}) as Record<string, unknown>;
  const params = (root.Params ?? {}) as Record<string, unknown>;

  const container = (docker.Container ?? {}) as Record<string, unknown>;
  const network = (docker.Network ?? {}) as Record<string, unknown>;
  const runtime = (docker.Runtime ?? {}) as Record<string, unknown>;
  const resources = (docker.Resources ?? {}) as Record<string, unknown>;
  const environments = (docker.Environments ?? {}) as Record<string, unknown>;
  const rawMounts = Array.isArray(docker.Mounts) ? docker.Mounts : [];

  const mounts: MountEntry[] = rawMounts
    .filter((m): m is Record<string, unknown> => !!m && typeof m === "object")
    .map((m) => ({
      source: typeof m.source === "string" ? m.source : "",
      target: typeof m.target === "string" ? m.target : "",
      readonly: m.readonly === true,
    }));

  const state: ParamsState = {
    slug,
    container: {
      Name:
        typeof container.Name === "string"
          ? container.Name
          : fallback.container.Name,
      Image:
        typeof container.Image === "string"
          ? container.Image
          : fallback.container.Image,
    },
    network: {
      Mode:
        typeof network.Mode === "string" ? network.Mode : fallback.network.Mode,
    },
    runtime: {
      Init: runtime.Init === true || runtime.Init === undefined,
      StopSignal:
        typeof runtime.StopSignal === "string"
          ? runtime.StopSignal
          : fallback.runtime.StopSignal,
      StopTimeout:
        typeof runtime.StopTimeout === "number"
          ? runtime.StopTimeout
          : fallback.runtime.StopTimeout,
      WorkingDir:
        typeof runtime.WorkingDir === "string"
          ? runtime.WorkingDir
          : fallback.runtime.WorkingDir,
    },
    resources: {
      Memory:
        typeof resources.Memory === "string"
          ? resources.Memory
          : fallback.resources.Memory,
      Cpus:
        typeof resources.Cpus === "string"
          ? resources.Cpus
          : fallback.resources.Cpus,
    },
    environments: recordToEntries(environments),
    mounts,
    params: recordToEntries(params),
    testOverrides: recordToEntries((root.TestOverrides ?? {}) as Record<string, unknown>),
    excluded: {
      environments: Array.isArray((root.Excluded as Record<string, unknown>)?.environments)
        ? ((root.Excluded as Record<string, unknown>).environments as string[])
        : [],
      mounts: Array.isArray((root.Excluded as Record<string, unknown>)?.mounts)
        ? ((root.Excluded as Record<string, unknown>).mounts as string[])
        : [],
      params: Array.isArray((root.Excluded as Record<string, unknown>)?.params)
        ? ((root.Excluded as Record<string, unknown>).params as string[])
        : [],
    },
    _extra: {},
  };

  // Preserve unknown top-level keys (Target, Generation, etc.)
  const knownKeys = new Set(["docker", "Params", "TestOverrides", "Excluded"]);
  for (const [k, v] of Object.entries(root)) {
    if (!knownKeys.has(k)) state._extra[k] = v;
  }

  return { state, parseError: null };
}

function serialize(state: ParamsState): string {
  const output = {
    docker: {
      Container: { ...state.container },
      Network: { ...state.network },
      Runtime: { ...state.runtime },
      Resources: { ...state.resources },
      Environments: entriesToRecord(state.environments),
      Mounts: state.mounts
        .filter((m) => m.source.trim() && m.target.trim())
        .map((m) => ({
          source: m.source,
          target: m.target,
          readonly: m.readonly,
        })),
    },
    Params: entriesToRecord(state.params),
    ...(state.testOverrides.length > 0
      ? { TestOverrides: entriesToRecord(state.testOverrides) }
      : {}),
    ...(state.excluded.environments.length || state.excluded.mounts.length || state.excluded.params.length
      ? {
          Excluded: {
            ...(state.excluded.environments.length ? { environments: state.excluded.environments } : {}),
            ...(state.excluded.mounts.length ? { mounts: state.excluded.mounts } : {}),
            ...(state.excluded.params.length ? { params: state.excluded.params } : {}),
          },
        }
      : {}),
    ...state._extra,
  };
  return `${JSON.stringify(output, null, 2)}\n`;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dockerfileId: string;
  file: FileSummary | null;
  onSaved: () => void;
}

export function DockerfileParamsDialog({
  open,
  onOpenChange,
  dockerfileId,
  file,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [state, setState] = useState<ParamsState>(DEFAULT_STATE(dockerfileId));
  const [parseError, setParseError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState("container");
  const [mountChecks, setMountChecks] = useState<MountCheckResult[]>([]);

  useEffect(() => {
    if (!open || !file) return;
    const { state: parsed, parseError: err } = parseContent(
      file.content,
      dockerfileId,
    );
    setState(parsed);
    setParseError(err);
    setSaveError(null);
    setSaving(false);
    setTab("container");
  }, [open, file, dockerfileId]);

  const displayName = useMemo(
    () => substituteSlug(state.container.Name, state.slug),
    [state.container.Name, state.slug],
  );
  const displayImage = useMemo(
    () => substituteSlug(state.container.Image, state.slug),
    [state.container.Image, state.slug],
  );
  const [previewTest, setPreviewTest] = useState(true);
  const dockerCommand = useMemo(
    () => buildDockerRunCommand(state, previewTest),
    [state, previewTest],
  );
  const dockerTokens = useMemo(() => highlightBash(dockerCommand), [dockerCommand]);

  // Debounced mount-existence check — hits the backend to resolve + stat each
  // mount source. Only runs when the dialog is open and something relevant
  // changes.
  useEffect(() => {
    if (!open) return;
    const handle = window.setTimeout(async () => {
      try {
        const res = await dockerfilesApi.checkMounts(dockerfileId, {
          mounts: state.mounts.map((m) => ({
            source: m.source,
            target: m.target,
            readonly: m.readonly,
          })),
          params: entriesToRecord(state.params),
        });
        setMountChecks(res.results);
      } catch {
        setMountChecks([]);
      }
    }, 400);
    return () => window.clearTimeout(handle);
  }, [open, dockerfileId, state.mounts, state.params]);

  function updateNetwork(patch: Partial<NetworkState>) {
    setState((prev) => ({ ...prev, network: { ...prev.network, ...patch } }));
  }
  function updateRuntime(patch: Partial<RuntimeState>) {
    setState((prev) => ({ ...prev, runtime: { ...prev.runtime, ...patch } }));
  }
  function updateResources(patch: Partial<ResourcesState>) {
    setState((prev) => ({ ...prev, resources: { ...prev.resources, ...patch } }));
  }

  function addKV(section: "environments" | "params") {
    setState((prev) => ({
      ...prev,
      [section]: [...prev[section], { key: "", value: "" }],
    }));
  }
  function updateKV(
    section: "environments" | "params",
    idx: number,
    patch: Partial<KVEntry>,
  ) {
    setState((prev) => ({
      ...prev,
      [section]: prev[section].map((e, i) =>
        i === idx ? { ...e, ...patch } : e,
      ),
    }));
  }
  function removeKV(section: "environments" | "params", idx: number) {
    setState((prev) => ({
      ...prev,
      [section]: prev[section].filter((_, i) => i !== idx),
    }));
  }

  function addMount() {
    setState((prev) => ({
      ...prev,
      mounts: [
        ...prev.mounts,
        { source: "", target: "", readonly: false },
      ],
    }));
  }
  function updateMount(idx: number, patch: Partial<MountEntry>) {
    setState((prev) => ({
      ...prev,
      mounts: prev.mounts.map((m, i) => (i === idx ? { ...m, ...patch } : m)),
    }));
  }
  function removeMount(idx: number) {
    setState((prev) => ({
      ...prev,
      mounts: prev.mounts.filter((_, i) => i !== idx),
    }));
  }

  function validate(): string | null {
    for (const e of state.environments) {
      const err = validateEnvKey(e.key.trim());
      if (err) {
        return t("dockerfiles.params.error_invalid_key_in", {
          section: t("dockerfiles.params.tab_environments"),
          key: e.key.trim(),
        });
      }
    }
    for (const e of state.params) {
      const err = validateEnvKey(e.key.trim());
      if (err) {
        return t("dockerfiles.params.error_invalid_key_in", {
          section: t("dockerfiles.params.tab_params"),
          key: e.key.trim(),
        });
      }
    }
    const envKeys = state.environments.map((e) => e.key.trim()).filter(Boolean);
    const envDupes = envKeys.filter((k, i) => envKeys.indexOf(k) !== i);
    if (envDupes.length > 0) {
      return t("dockerfiles.params.error_duplicate_key_in", {
        section: t("dockerfiles.params.tab_environments"),
        key: envDupes[0],
      });
    }
    const paramKeys = state.params.map((e) => e.key.trim()).filter(Boolean);
    const paramDupes = paramKeys.filter((k, i) => paramKeys.indexOf(k) !== i);
    if (paramDupes.length > 0) {
      return t("dockerfiles.params.error_duplicate_key_in", {
        section: t("dockerfiles.params.tab_params"),
        key: paramDupes[0],
      });
    }
    const timeout = state.runtime.StopTimeout;
    if (!Number.isFinite(timeout) || timeout < 0 || timeout > 600) {
      return t("dockerfiles.params.error_stop_timeout_range");
    }
    return null;
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const err = validate();
    if (err) {
      setSaveError(err);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      await dockerfilesApi.updateFile(dockerfileId, file.id, serialize(state));
      onSaved();
      onOpenChange(false);
    } catch (caught: unknown) {
      const detail = (caught as { response?: { data?: { detail?: string } } })
        .response?.data?.detail;
      setSaveError(detail ?? t("dockerfiles.params.error_save"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:w-[1200px] sm:max-w-[95vw] sm:h-[760px] sm:max-h-[92vh] flex flex-col overflow-hidden p-0">
        <form
          onSubmit={handleSubmit}
          className="flex flex-col h-full min-h-0"
        >
          <DialogHeader className="px-6 pt-6 pb-3 border-b">
            <DialogTitle>{t("dockerfiles.params.dialog_title")}</DialogTitle>
            <DialogDescription>
              {t("dockerfiles.params.dialog_subtitle")}
            </DialogDescription>
          </DialogHeader>

          <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            {/* Left: tabs with form controls */}
            <div className="min-h-0 overflow-y-auto px-6 py-4 space-y-4 border-r">
              {parseError && (
                <p className="text-[12px] text-destructive" role="alert">
                  {t(`dockerfiles.params.error_${parseError}`)}
                </p>
              )}

              <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="flex flex-wrap h-auto">
              <TabsTrigger value="container">
                {t("dockerfiles.params.tab_container")}
              </TabsTrigger>
              <TabsTrigger value="network">
                {t("dockerfiles.params.tab_network")}
              </TabsTrigger>
              <TabsTrigger value="runtime">
                {t("dockerfiles.params.tab_runtime")}
              </TabsTrigger>
              <TabsTrigger value="resources">
                {t("dockerfiles.params.tab_resources")}
              </TabsTrigger>
              <TabsTrigger value="environments">
                {t("dockerfiles.params.tab_environments")}
              </TabsTrigger>
              <TabsTrigger value="mounts">
                {t("dockerfiles.params.tab_mounts")}
              </TabsTrigger>
              <TabsTrigger value="params">
                {t("dockerfiles.params.tab_params")}
              </TabsTrigger>
              <TabsTrigger value="test">
                {t("dockerfiles.params.tab_test")}
              </TabsTrigger>
            </TabsList>

            {/* Container */}
            <TabsContent value="container" className="space-y-4">
              <div className="flex flex-col gap-1.5">
                <Label>{t("dockerfiles.params.container_name")}</Label>
                <Input
                  value={displayName}
                  disabled
                  className="font-mono text-[12px]"
                />
                <p className="text-[11px] text-muted-foreground">
                  {t("dockerfiles.params.container_name_hint")}
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>{t("dockerfiles.params.container_image")}</Label>
                <Input
                  value={displayImage}
                  disabled
                  className="font-mono text-[12px]"
                />
                <p className="text-[11px] text-muted-foreground">
                  {t("dockerfiles.params.container_image_hint")}
                </p>
              </div>
            </TabsContent>

            {/* Network */}
            <TabsContent value="network" className="space-y-4">
              <div className="flex flex-col gap-1.5">
                <Label>{t("dockerfiles.params.network_mode")}</Label>
                <Select
                  value={deriveNetworkType(state.network.Mode)}
                  onValueChange={(v) => {
                    if (v === "custom") {
                      // Clear Mode so the custom input takes over; user will type a name.
                      updateNetwork({ Mode: "" });
                    } else {
                      updateNetwork({ Mode: v });
                    }
                  }}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BUILTIN_NETWORK_MODES.map((m) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                    <SelectItem value="custom">
                      {t("dockerfiles.params.network_mode_custom")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {deriveNetworkType(state.network.Mode) === "custom" && (
                <div className="flex flex-col gap-1.5">
                  <Label>{t("dockerfiles.params.network_custom_label")}</Label>
                  <Input
                    value={state.network.Mode}
                    onChange={(e) => updateNetwork({ Mode: e.target.value })}
                    placeholder={t("dockerfiles.params.network_custom_ph")}
                    className="font-mono text-[12px]"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    {t("dockerfiles.params.network_custom_hint")}
                  </p>
                </div>
              )}
            </TabsContent>

            {/* Runtime */}
            <TabsContent value="runtime" className="space-y-4">
              <div className="flex items-center gap-3">
                <input
                  id="runtime-init"
                  type="checkbox"
                  checked={state.runtime.Init}
                  onChange={(e) => updateRuntime({ Init: e.target.checked })}
                  className="h-4 w-4 rounded border border-input accent-primary"
                />
                <Label htmlFor="runtime-init" className="cursor-pointer">
                  {t("dockerfiles.params.runtime_init")}
                </Label>
              </div>
              <p className="text-[11px] text-muted-foreground -mt-2 ml-7">
                {t("dockerfiles.params.runtime_init_hint")}
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label>{t("dockerfiles.params.runtime_stop_signal")}</Label>
                  <Select
                    value={state.runtime.StopSignal}
                    onValueChange={(v) => updateRuntime({ StopSignal: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STOP_SIGNALS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t("dockerfiles.params.runtime_stop_timeout")}</Label>
                  <Input
                    type="number"
                    min={0}
                    max={600}
                    value={state.runtime.StopTimeout}
                    onChange={(e) =>
                      updateRuntime({ StopTimeout: Number(e.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label>{t("dockerfiles.params.runtime_working_dir")}</Label>
                <Input
                  value={state.runtime.WorkingDir}
                  onChange={(e) => updateRuntime({ WorkingDir: e.target.value })}
                  className="font-mono text-[12px]"
                />
              </div>
            </TabsContent>

            {/* Resources */}
            <TabsContent value="resources" className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <Label>{t("dockerfiles.params.resources_memory")}</Label>
                  {(() => {
                    const { numeric, unit } = parseMemory(state.resources.Memory);
                    return (
                      <div className="flex gap-2">
                        <Input
                          type="number"
                          min={0}
                          step={1}
                          value={numeric}
                          onChange={(e) =>
                            updateResources({
                              Memory: buildMemory(e.target.value, unit),
                            })
                          }
                          placeholder="0"
                          className="font-mono text-[12px] flex-1"
                        />
                        <Select
                          value={unit}
                          onValueChange={(v) =>
                            updateResources({
                              Memory: buildMemory(numeric, v as MemoryUnit),
                            })
                          }
                        >
                          <SelectTrigger className="w-20">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {MEMORY_UNITS.map((u) => (
                              <SelectItem key={u} value={u}>
                                {u === "m" ? "MB" : "GB"}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    );
                  })()}
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>{t("dockerfiles.params.resources_cpus")}</Label>
                  <Input
                    type="number"
                    min={0}
                    step={0.1}
                    value={state.resources.Cpus}
                    onChange={(e) =>
                      updateResources({ Cpus: e.target.value })
                    }
                    placeholder="0"
                    className="font-mono text-[12px]"
                  />
                </div>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {t("dockerfiles.params.resources_hint")}
              </p>
            </TabsContent>

            {/* Environments */}
            <TabsContent value="environments" className="space-y-2">
              <p className="text-[11px] text-muted-foreground px-1">
                {t("dockerfiles.params.environments_hint")}
              </p>
              <KVTable
                entries={state.environments}
                onUpdate={(idx, patch) => updateKV("environments", idx, patch)}
                onRemove={(idx) => removeKV("environments", idx)}
                onAdd={() => addKV("environments")}
                keyPlaceholder="ANTHROPIC_API_KEY"
                valuePlaceholder="{API_KEY_NAME}"
                emptyLabel={t("dockerfiles.params.environments_empty")}
                addLabel={t("dockerfiles.params.environments_add")}
                removeLabel={t("dockerfiles.params.remove")}
                validateKey={validateEnvKey}
                keyErrorHint={t("dockerfiles.params.env_key_error")}
                excludedKeys={state.excluded.environments}
                onToggleExclude={(key) => {
                  const list = state.excluded.environments;
                  const next = list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
                  setState((s) => ({ ...s, excluded: { ...s.excluded, environments: next } }));
                }}
              />
            </TabsContent>

            {/* Mounts */}
            <TabsContent value="mounts" className="space-y-2">
              {state.mounts.length === 0 && (
                <p className="text-[12px] italic text-muted-foreground px-1">
                  {t("dockerfiles.params.mounts_empty")}
                </p>
              )}
              <p className="text-[11px] text-muted-foreground px-1">
                {t("dockerfiles.params.mounts_hint")}
              </p>
              <div className="grid grid-cols-[auto_auto_minmax(0,1fr)_minmax(0,1fr)_2rem_2rem] gap-2 px-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                <span className="text-[9px] -ml-2">excl.</span>
                <span className="sr-only">
                  {t("dockerfiles.params.mount_status")}
                </span>
                <span>{t("dockerfiles.params.mount_source")}</span>
                <span>{t("dockerfiles.params.mount_target")}</span>
                <span className="text-center pl-4">
                  {t("dockerfiles.params.mount_readonly")}
                </span>
                <span className="sr-only">
                  {t("dockerfiles.params.remove")}
                </span>
              </div>
              {state.mounts.map((m, idx) => {
                // mountChecks is index-aligned with non-empty mounts, but
                // we get it filtered server-side; match by source_original.
                const check = mountChecks.find(
                  (c) => c.source_original === m.source.trim(),
                );
                const status: "ok" | "missing" | "unknown" | "empty" =
                  !m.source.trim()
                    ? "empty"
                    : check?.exists === true
                      ? "ok"
                      : check?.exists === false
                        ? "missing"
                        : "unknown";
                const dotClass =
                  status === "ok"
                    ? "bg-emerald-500"
                    : status === "missing"
                      ? "bg-red-500"
                      : "bg-zinc-500";
                const titleText =
                  status === "ok"
                    ? t("dockerfiles.params.mount_status_ok", {
                        path: check?.source_resolved ?? "",
                      })
                    : status === "missing"
                      ? t("dockerfiles.params.mount_status_missing", {
                          path: check?.source_resolved ?? "",
                        })
                      : status === "unknown"
                        ? t("dockerfiles.params.mount_status_unknown")
                        : "";
                const isMountExcluded = state.excluded.mounts.includes(m.target);
                return (
                  <div key={idx} className={isMountExcluded ? "opacity-40" : ""}>
                    <div className="grid grid-cols-[auto_auto_minmax(0,1fr)_minmax(0,1fr)_2rem_2rem] gap-2 items-center">
                      <input
                        type="checkbox"
                        checked={isMountExcluded}
                        onChange={() => {
                          const list = state.excluded.mounts;
                          const next = list.includes(m.target) ? list.filter((t) => t !== m.target) : [...list, m.target];
                          setState((s) => ({ ...s, excluded: { ...s.excluded, mounts: next } }));
                        }}
                        title="Exclure"
                        className="h-3.5 w-3.5 accent-primary"
                      />
                      <span
                        className={cn(
                          "w-2 h-2 rounded-full shrink-0 justify-self-center",
                          dotClass,
                        )}
                        title={titleText}
                        aria-label={titleText}
                      />
                      <Input
                        value={m.source}
                        onChange={(e) =>
                          updateMount(idx, { source: e.target.value })
                        }
                        placeholder="auth.json"
                        className="font-mono text-[12px]"
                      />
                      <Input
                        value={m.target}
                        onChange={(e) =>
                          updateMount(idx, { target: e.target.value })
                        }
                        placeholder="/app/target"
                        className="font-mono text-[12px]"
                      />
                      <input
                        type="checkbox"
                        checked={m.readonly}
                        onChange={(e) =>
                          updateMount(idx, { readonly: e.target.checked })
                        }
                        aria-label={t("dockerfiles.params.mount_readonly")}
                        className="h-4 w-4 rounded border border-input accent-primary justify-self-center ml-4"
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeMount(idx)}
                        aria-label={t("dockerfiles.params.remove")}
                      >
                        <X className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                    {check && (
                      <div className="text-[10px] mt-1 ml-6 space-y-0.5">
                        <p className="font-mono truncate text-muted-foreground">
                          →{" "}
                          <span
                            className={cn(
                              status === "missing" && "text-destructive",
                              status === "ok" && "text-emerald-400",
                            )}
                          >
                            {check.source_resolved}
                          </span>
                          {check.auto_prefixed && (
                            <span className="text-muted-foreground ml-2">
                              ({t("dockerfiles.params.mount_auto_prefixed")})
                            </span>
                          )}
                        </p>
                        {status === "missing" && (
                          <p className="text-destructive">
                            {mountMissingExplanation(
                              check.source_resolved,
                              check.auto_prefixed,
                              t,
                            )}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addMount}
              >
                <Plus className="w-3.5 h-3.5" />
                {t("dockerfiles.params.mounts_add")}
              </Button>
            </TabsContent>

            {/* Params */}
            <TabsContent value="params" className="space-y-2">
              <p className="text-[11px] text-muted-foreground px-1">
                {t("dockerfiles.params.params_hint")}
              </p>
              <KVTable
                entries={state.params}
                onUpdate={(idx, patch) => updateKV("params", idx, patch)}
                onRemove={(idx) => removeKV("params", idx)}
                onAdd={() => addKV("params")}
                keyPlaceholder="WORKSPACE_PATH"
                valuePlaceholder="${WORKSPACE_PATH:-./workspace}"
                emptyLabel={t("dockerfiles.params.params_empty")}
                addLabel={t("dockerfiles.params.params_add")}
                removeLabel={t("dockerfiles.params.remove")}
                validateKey={validateEnvKey}
                keyErrorHint={t("dockerfiles.params.env_key_error")}
                excludedKeys={state.excluded.params}
                onToggleExclude={(key) => {
                  const list = state.excluded.params;
                  const next = list.includes(key) ? list.filter((k) => k !== key) : [...list, key];
                  setState((s) => ({ ...s, excluded: { ...s.excluded, params: next } }));
                }}
              />
            </TabsContent>

            {/* Test overrides */}
            <TabsContent value="test" className="space-y-2">
              <p className="text-[11px] text-muted-foreground px-1">
                {t("dockerfiles.params.test_hint")}
              </p>
              <KVTable
                entries={state.testOverrides}
                onUpdate={(idx, patch) => {
                  const next = [...state.testOverrides];
                  next[idx] = { ...next[idx]!, ...patch };
                  setState((s) => ({ ...s, testOverrides: next }));
                }}
                onRemove={(idx) => {
                  setState((s) => ({
                    ...s,
                    testOverrides: s.testOverrides.filter((_, i) => i !== idx),
                  }));
                }}
                onAdd={() => {
                  setState((s) => ({
                    ...s,
                    testOverrides: [...s.testOverrides, { key: "", value: "" }],
                  }));
                }}
                keyPlaceholder="MISTRAL_API_KEY"
                valuePlaceholder="sk-test-..."
                emptyLabel={t("dockerfiles.params.test_empty")}
                addLabel={t("dockerfiles.params.test_add")}
                removeLabel={t("dockerfiles.params.remove")}
              />
            </TabsContent>
          </Tabs>
            </div>

            {/* Right: live command preview */}
            <div className="min-h-0 flex flex-col bg-muted">
              <div className="px-4 pt-4 pb-2 border-b border-border flex items-center justify-between shrink-0">
                <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {t("dockerfiles.params.preview_title")}
                </span>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={previewTest}
                    onChange={(e) => setPreviewTest(e.target.checked)}
                    className="h-3 w-3 accent-primary"
                  />
                  <span className="text-[10px] text-muted-foreground">
                    {t("dockerfiles.params.preview_test_mode")}
                  </span>
                </label>
              </div>
              <pre className="flex-1 min-h-0 overflow-auto p-4 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-all">
                {dockerTokens.map((tok, i) => (
                  <span key={i} className={tok.cls}>
                    {tok.text}
                  </span>
                ))}
              </pre>
            </div>
          </div>

          <div className="px-6 py-3 border-t shrink-0 space-y-2">
            {saveError && (
              <p className="text-[12px] text-destructive" role="alert">
                {saveError}
              </p>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => onOpenChange(false)}
                disabled={saving}
              >
                {t("common.cancel")}
              </Button>
              <Button type="submit" disabled={saving || !file}>
                {t("dockerfiles.params.save")}
              </Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

interface KVTableProps {
  entries: KVEntry[];
  onUpdate: (idx: number, patch: Partial<KVEntry>) => void;
  onRemove: (idx: number) => void;
  onAdd: () => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
  emptyLabel: string;
  addLabel: string;
  removeLabel: string;
  validateKey?: (key: string) => string | null;
  keyErrorHint?: string;
  excludedKeys?: string[];
  onToggleExclude?: (key: string) => void;
}

function KVTable({
  entries,
  onUpdate,
  onRemove,
  onAdd,
  keyPlaceholder,
  valuePlaceholder,
  emptyLabel,
  addLabel,
  removeLabel,
  validateKey,
  keyErrorHint,
  excludedKeys,
  onToggleExclude,
}: KVTableProps) {
  return (
    <>
      {entries.length === 0 && (
        <p className="text-[12px] italic text-muted-foreground px-1">
          {emptyLabel}
        </p>
      )}
      <div className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1.4fr)_auto] gap-2 px-1 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
        {onToggleExclude ? <span className="text-[9px] -ml-2">excl.</span> : <span />}
        <span>key</span>
        <span>value</span>
        <span className="sr-only">{removeLabel}</span>
      </div>
      {entries.map((entry, idx) => {
        const keyError =
          validateKey && entry.key.length > 0 ? validateKey(entry.key) : null;
        const isExcluded = excludedKeys?.includes(entry.key) ?? false;
        return (
          <div key={idx} className={isExcluded ? "opacity-40" : ""}>
            <div className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1.4fr)_auto] gap-2 items-center">
              {onToggleExclude ? (
                <input
                  type="checkbox"
                  checked={isExcluded}
                  onChange={() => onToggleExclude(entry.key)}
                  title="Exclure"
                  className="h-3.5 w-3.5 accent-primary"
                />
              ) : <span />}
              <Input
                value={entry.key}
                onChange={(e) => onUpdate(idx, { key: e.target.value })}
                placeholder={keyPlaceholder}
                aria-invalid={keyError ? true : undefined}
                className={cn(
                  "font-mono text-[12px]",
                  keyError &&
                    "border-destructive focus-visible:ring-destructive/30 focus-visible:border-destructive",
                )}
              />
              <Input
                value={entry.value}
                onChange={(e) => onUpdate(idx, { value: e.target.value })}
                placeholder={valuePlaceholder}
                className="font-mono text-[12px]"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => onRemove(idx)}
                aria-label={removeLabel}
              >
                <X className="w-3.5 h-3.5" />
              </Button>
            </div>
            {keyError && (
              <p className="text-[11px] text-destructive mt-1 ml-1">
                {keyErrorHint ?? keyError}
              </p>
            )}
          </div>
        );
      })}
      <Button type="button" variant="outline" size="sm" onClick={onAdd}>
        <Plus className="w-3.5 h-3.5" />
        {addLabel}
      </Button>
    </>
  );
}
