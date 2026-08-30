import {
  type Component,
  Input,
  type MouseRoutable,
  routeSgrMouseInput,
  type SgrMouseEvent,
  type TUI,
  truncateToWidth,
} from "@oh-my-pi/pi-tui";

import {
  BASELINE_MODES,
  FAMILY_STATES,
  RULE_STATES,
  allowedBaseline,
  allowedFamilyState,
  allowedRuleState,
} from "./adw-bridge";
import type {
  AdwPolicyState,
  BaselineMode,
  GateState,
  RuleState,
} from "./adw-bridge";

export {
  AdwBridgeError,
  bridgeResponseError,
  createConfigureBridgeRunner,
  decodeAdwPolicy,
  runConfigureBridge,
} from "./adw-bridge";
export type {
  AdwBridgeOperation,
  AdwBridgeResponse,
  AdwBridgeRunner,
  AdwConfigureRequest,
  AdwFamilyMetadata,
  AdwPolicyState,
  AdwRuleMetadata,
  AdwRuntimeStatus,
} from "./adw-bridge";

export type AdwConfigOutcome = "saved" | "cancelled";

export interface AdwConfigCallbacks {
  close: (outcome: AdwConfigOutcome) => void;
  requestRender: () => void;
  notify: (message: string, type?: "info" | "warning" | "error") => void;
  save: (expectedDigest: string | null, values: Record<string, unknown>) => Promise<AdwPolicyState | void>;
  availableModels?: readonly string[];
}

/** Narrow unknown bridge and draft values to object records. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Remove terminal controls and collapse line breaks before data reaches the TUI. */
export function sanitizeDisplay(value: unknown, limit = 512): string {
  const text = typeof value === "string" ? value : value == null ? "" : String(value);
  return text
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "")
    .replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

/** Accept only bounded, control-free policy strings from bridge data. */
export function safePolicyString(value: unknown, limit = 4096): string | undefined {
  if (typeof value !== "string" || value.length === 0 || value.length > limit) return undefined;
  if (/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/.test(value)) return undefined;
  return value;
}
type Screen = "menu" | "models" | "families" | "rules" | "thresholds" | "baseline" | "exemptions" | "kill" | "boundary" | "runtime" | "input";
type InputKind = "max_rows" | "sentence_word_cap" | "list_item_cap" | "exempt_paths" | "exempt_families";
interface Row {
  id: string;
  label: string;
  detail?: string;
  locked?: boolean;
}

function copyValues(values: Record<string, unknown>): Record<string, unknown> {
  const output: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) output[key] = value.slice();
    else if (isRecord(value)) output[key] = copyValues(value);
    else if (["string", "number", "boolean"].includes(typeof value) || value === null) output[key] = value;
  }
  return output;
}

/** Fullscreen editor for known ADW policy values. */
export class AdwConfigOverlayComponent implements Component, MouseRoutable {
  #tui: TUI;
  #state: AdwPolicyState;
  #draft: Record<string, unknown>;
  #callbacks: AdwConfigCallbacks;
  #screen: Screen = "menu";
  #returnScreen: Screen = "menu";
  #cursor = 0;
  #scroll = 0;
  #dirty = false;
  #saving = false;
  #status = "";
  #input: Input | undefined;
  #inputKind: InputKind | undefined;
  #availableModels: readonly string[];

  constructor(tui: TUI, state: AdwPolicyState, callbacks: AdwConfigCallbacks) {
    this.#tui = tui;
    this.#state = state;
    this.#draft = copyValues(state.values);
    this.#availableModels = callbacks.availableModels ?? [];
    this.#callbacks = callbacks;
  }

  debugState(): Record<string, unknown> {
    return {
      screen: this.#screen,
      dirty: this.#dirty,
      saving: this.#saving,
      cursor: this.#cursor,
      fieldCount: this.#rows().length,
    };
  }

  render(width: number): readonly string[] {
    const safeWidth = Math.max(24, Math.trunc(width));
    const height = Math.max(16, Number(process.stdout.rows) || 24);
    const bodyRows = Math.max(5, height - 4);
    const title = `ADW configuration${this.#dirty ? " * unsaved" : ""}`;
    const output = [`+${"-".repeat(Math.max(1, safeWidth - 2))}+`];
    output.push(this.#frameLine(title, safeWidth));
    if (this.#screen === "input" && this.#input) {
      output.push(this.#frameLine(this.#inputTitle(), safeWidth));
      const inputLines = this.#input.render(Math.max(1, safeWidth - 4));
      for (let index = 0; index < bodyRows - 1; index++) output.push(this.#frameLine(inputLines[index] ?? "", safeWidth));
      output.push(this.#frameLine(this.#footer(), safeWidth));
      output.push(`+${"-".repeat(Math.max(1, safeWidth - 2))}+`);
      return output;
    }
    const rows = this.#rows();
    this.#keepCursorVisible(rows.length, bodyRows);
    for (let index = 0; index < bodyRows; index++) {
      const row = rows[this.#scroll + index];
      if (!row) {
        output.push(this.#frameLine("", safeWidth));
        continue;
      }
      const marker = this.#scroll + index === this.#cursor ? "> " : "  ";
      const lock = row.locked ? " [locked]" : "";
      output.push(this.#frameLine(`${marker}${row.label}${lock}${row.detail ? `  ${row.detail}` : ""}`, safeWidth));
    }
    output.push(this.#frameLine(this.#footer(), safeWidth));
    output.push(`+${"-".repeat(Math.max(1, safeWidth - 2))}+`);
    return output;
  }

  handleInput(data: string): void {
    if (this.#screen === "input" && this.#input) {
      this.#input.handleInput(data);
      this.#callbacks.requestRender();
      return;
    }
    if (data.startsWith("\x1b[<")) {
      routeSgrMouseInput(data, event => this.#routeMouse(event));
      return;
    }
    if (data === "\x1b[A" || data === "\x10") {
      this.#moveCursor(-1);
      return;
    }
    if (data === "\x1b[B" || data === "\x0e") {
      this.#moveCursor(1);
      return;
    }
    if (data === "\x1b[5~") {
      this.#moveCursor(-5);
      return;
    }
    if (data === "\x1b[6~") {
      this.#moveCursor(5);
      return;
    }
    if (data === "\x1b" || data === "\x03") {
      if (this.#screen === "menu") this.#callbacks.close("cancelled");
      else this.#setScreen("menu");
      return;
    }
    if (data === "\r" || data === "\n" || data === " ") {
      const row = this.#rows()[this.#cursor];
      if (row) void this.#activate(row);
    }
  }

  routeMouse(event: SgrMouseEvent, line: number, _column: number): void {
    if (this.#screen === "input") return;
    if (event.wheel !== null) {
      this.#moveCursor(event.wheel);
      return;
    }
    if (!event.leftClick || line < 2) return;
    const index = this.#scroll + line - 2;
    const row = this.#rows()[index];
    if (!row) return;
    this.#cursor = index;
    void this.#activate(row);
  }

  #routeMouse(event: SgrMouseEvent): boolean {
    this.routeMouse(event, event.row, event.col);
    return true;
  }

  #frameLine(value: string, width: number): string {
    const content = truncateToWidth(sanitizeDisplay(value, 2048), Math.max(1, width - 4));
    return `| ${content.padEnd(Math.max(0, width - 4), " ")} |`;
  }

  #inputTitle(): string {
    const kind = this.#inputKind;
    if (kind === "exempt_paths") return "Exempt paths, comma-separated";
    if (kind === "exempt_families") return "Exempt family patterns, pattern=family1,family2; ...";
    return `Edit ${kind ?? "value"}`;
  }

  #footer(): string {
    if (this.#status) return this.#status;
    if (this.#saving) return "Saving policy...";
    if (this.#screen === "menu") return "Arrow keys or mouse move · Enter edits · Save writes · Esc cancels";
    if (this.#screen === "runtime") return "Runtime values are read-only and redacted · Esc back";
    if (this.#screen === "input") return "Type a value · Enter apply · Esc cancel";
    return "Arrow keys or mouse move · Enter changes · Esc back";
  }

  #rows(): Row[] {
    if (this.#screen === "menu") {
      return [
        { id: "families", label: "Family gates", detail: `${this.#state.families.length} families` },
        { id: "rules", label: "Per-rule gates", detail: `${this.#state.rules.length} rules` },
        { id: "thresholds", label: "Thresholds" },
        { id: "baseline", label: "Baseline mode", detail: this.#baseline() },
        { id: "exemptions", label: "Exemptions", detail: this.#exemptionSummary() },
        { id: "kill", label: "Kill switches" },
        { id: "boundary", label: "Data boundary", detail: this.#boundaryEnabled() ? "enabled" : "disabled" },
        { id: "models", label: "ADW model", detail: this.#modelState() },
        { id: "runtime", label: "Runtime status", detail: "read-only" },
        { id: "save", label: "Save policy", detail: this.#dirty ? "write changes" : "write current values" },
        { id: "cancel", label: "Cancel" },
      ];
    }
    if (this.#screen === "models") {
      return [
        ...this.#availableModels.map(model => ({
          id: `model:${model}`,
          label: model,
          detail: model === this.#modelState() ? "selected" : undefined,
        })),
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "families") {
      return [
        ...this.#state.families.map(family => ({ id: `family:${family.name}`, label: family.name, detail: this.#familyState(family.name) })),
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "rules") {
      return [
        ...this.#state.rules.map(rule => ({ id: `rule:${rule.name}`, label: rule.name, detail: this.#ruleState(rule.name), locked: rule.locked })),
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "thresholds") {
      return [
        { id: "threshold:max_rows", label: "max_rows", detail: String(this.#numberValue("max_rows", 8)) },
        { id: "threshold:sentence_word_cap", label: "sentence_word_cap", detail: String(this.#numberValue("sentence_word_cap", 40)) },
        { id: "threshold:list_item_cap", label: "list_item_cap", detail: String(this.#numberValue("list_item_cap", 8)) },
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "baseline") return [{ id: "baseline:cycle", label: "Baseline mode", detail: this.#baseline() }, { id: "back", label: "Back" }];
    if (this.#screen === "exemptions") {
      return [
        { id: "exempt_paths", label: "Exempt paths", detail: this.#pathSummary() },
        { id: "exempt_families", label: "Exempt family patterns", detail: this.#familyExemptionSummary() },
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "kill") {
      return [
        ...this.#state.families.map(family => ({ id: `kill:${family.name}`, label: family.name, detail: this.#killState(family.name) })),
        { id: "back", label: "Back" },
      ];
    }
    if (this.#screen === "boundary") return [{ id: "boundary:toggle", label: "Data boundary", detail: this.#boundaryEnabled() ? "enabled" : "disabled" }, { id: "back", label: "Back" }];
    if (this.#screen === "runtime") {
      const python = this.#state.runtime.python;
      return [
        { id: "runtime:python", label: "ADW_PYTHON", detail: python.configured ? `configured (${python.executable || "configured"})` : "unset" },
        { id: "runtime:embedding", label: "Embedding provider", detail: this.#state.runtime.embedding.configured ? "configured" : "unset" },
        { id: "runtime:model", label: "Embedding model", detail: this.#state.runtime.embedding_model.configured ? "configured" : "unset" },
        { id: "back", label: "Back" },
      ];
    }
    return [];
  }

  #setScreen(screen: Screen): void {
    this.#screen = screen;
    this.#cursor = 0;
    this.#scroll = 0;
    this.#status = "";
    this.#callbacks.requestRender();
  }

  #keepCursorVisible(rowCount: number, bodyRows: number): void {
    if (rowCount === 0) {
      this.#cursor = 0;
      this.#scroll = 0;
      return;
    }
    this.#cursor = Math.max(0, Math.min(this.#cursor, rowCount - 1));
    if (this.#cursor < this.#scroll) this.#scroll = this.#cursor;
    if (this.#cursor >= this.#scroll + bodyRows) this.#scroll = this.#cursor - bodyRows + 1;
    this.#scroll = Math.max(0, Math.min(this.#scroll, Math.max(0, rowCount - bodyRows)));
  }

  #moveCursor(delta: number): void {
    const rows = this.#rows();
    if (rows.length === 0) return;
    this.#cursor = (this.#cursor + delta + rows.length) % rows.length;
    this.#callbacks.requestRender();
  }

  async #activate(row: Row): Promise<void> {
    if (this.#saving) return;
    if (row.locked) {
      this.#status = `${sanitizeDisplay(row.label)} is always blocking and cannot be changed`;
      this.#callbacks.notify(this.#status, "warning");
      this.#callbacks.requestRender();
      return;
    }
    if (row.id === "back") return this.#setScreen("menu");
    if (row.id === "cancel") return this.#callbacks.close("cancelled");
    if (row.id === "save") return this.#save();
    if (row.id === "models") return this.#setScreen("models");
    if (row.id.startsWith("model:")) return this.#selectModel(row.id.slice(6));
    if (row.id === "rules") return this.#setScreen("rules");
    if (row.id === "thresholds") return this.#setScreen("thresholds");
    if (row.id === "baseline") return this.#setScreen("baseline");
    if (row.id === "exemptions") return this.#setScreen("exemptions");
    if (row.id === "kill") return this.#setScreen("kill");
    if (row.id === "boundary") return this.#setScreen("boundary");
    if (row.id === "runtime") return this.#setScreen("runtime");
    if (row.id === "baseline:cycle") return this.#cycleBaseline();
    if (row.id === "boundary:toggle") return this.#toggleBoundary();
    if (row.id.startsWith("family:")) return this.#cycleFamily(row.id.slice(7));
    if (row.id.startsWith("rule:")) return this.#cycleRule(row.id.slice(5));
    if (row.id.startsWith("kill:")) return this.#toggleKill(row.id.slice(5));
    if (row.id === "exempt_paths") return this.#startInput("exempt_paths");
    if (row.id === "exempt_families") return this.#startInput("exempt_families");
    if (row.id.startsWith("threshold:")) return this.#startInput(row.id.slice(11) as InputKind);
  }

  #markDirty(): void {
    this.#dirty = true;
    this.#status = "";
    this.#callbacks.requestRender();
  }

  #modelState(): string {
    const value = this.#draft.adw_model;
    if (typeof value === "string" && value.trim()) return sanitizeDisplay(value, 180);
    const effective = this.#state.effective.adw_model;
    return typeof effective === "string" && effective.trim() ? sanitizeDisplay(effective, 180) : "default";
  }

  #selectModel(model: string): void {
    if (!this.#availableModels.includes(model)) return;
    this.#draft.adw_model = model;
    this.#markDirty();
  }
  #familyState(name: string): GateState {
    const gates = isRecord(this.#draft.gates) ? this.#draft.gates : {};
    const explicit = allowedFamilyState(gates[name]);
    return explicit ?? this.#state.familyStates[name] ?? "off";
  }

  #cycleFamily(name: string): void {
    const metadata = this.#state.families.find(family => family.name === name);
    if (!metadata) return;
    const states = metadata.states.length > 0 ? metadata.states : [...FAMILY_STATES];
    const current = this.#familyState(name);
    const next = states[(states.indexOf(current) + 1) % states.length] ?? states[0] ?? "off";
    this.#setNested("gates", name, next);
  }

  #ruleState(name: string): RuleState {
    const gates = isRecord(this.#draft.rule_gates) ? this.#draft.rule_gates : {};
    return allowedRuleState(gates[name]) ?? this.#state.ruleStates[name] ?? "observe";
  }

  #cycleRule(name: string): void {
    const metadata = this.#state.rules.find(rule => rule.name === name);
    if (!metadata || metadata.locked) return;
    const states = metadata.states.length > 0 ? metadata.states : [...RULE_STATES];
    const current = this.#ruleState(name);
    const next = states[(states.indexOf(current) + 1) % states.length] ?? states[0] ?? "observe";
    this.#setNested("rule_gates", name, next);
  }

  #killState(name: string): string {
    const switches = isRecord(this.#draft.kill_switches) ? this.#draft.kill_switches : {};
    return switches[name] === true ? "on" : "off";
  }

  #toggleKill(name: string): void {
    this.#setNested("kill_switches", name, this.#killState(name) !== "on");
  }

  #baseline(): BaselineMode {
    const value = allowedBaseline(this.#draft.baseline);
    if (value) return value;
    const effective = allowedBaseline(this.#state.effective.baseline);
    return effective ?? "report";
  }

  #cycleBaseline(): void {
    const current = this.#baseline();
    const next = BASELINE_MODES[(BASELINE_MODES.indexOf(current) + 1) % BASELINE_MODES.length] ?? "report";
    this.#draft.baseline = next;
    this.#markDirty();
  }

  #boundaryEnabled(): boolean {
    const boundary = isRecord(this.#draft.data_boundary) ? this.#draft.data_boundary : this.#state.effective.data_boundary;
    return isRecord(boundary) && boundary.enabled === true;
  }

  #toggleBoundary(): void {
    this.#setNested("data_boundary", "enabled", !this.#boundaryEnabled());
  }

  #numberValue(key: string, fallback: number): number {
    const draft = this.#draft[key];
    if (typeof draft === "number" && Number.isSafeInteger(draft)) return draft;
    const effective = this.#state.effective[key];
    return typeof effective === "number" && Number.isSafeInteger(effective) ? effective : fallback;
  }

  #pathSummary(): string {
    const paths = Array.isArray(this.#draft.exempt_paths) ? this.#draft.exempt_paths : this.#state.effective.exempt_paths;
    return Array.isArray(paths) && paths.length > 0 ? sanitizeDisplay(paths.join(", "), 180) : "(none)";
  }

  #familyExemptionSummary(): string {
    const mappings = isRecord(this.#draft.exempt_families) ? this.#draft.exempt_families : this.#state.effective.exempt_families;
    if (!isRecord(mappings) || Object.keys(mappings).length === 0) return "(none)";
    return sanitizeDisplay(Object.entries(mappings).map(([pattern, families]) => `${pattern}=${Array.isArray(families) ? families.join(",") : ""}`).join("; "), 180);
  }

  #exemptionSummary(): string {
    const paths = Array.isArray(this.#draft.exempt_paths) ? this.#draft.exempt_paths.length : 0;
    const families = isRecord(this.#draft.exempt_families) ? Object.keys(this.#draft.exempt_families).length : 0;
    return `${paths} paths, ${families} patterns`;
  }

  #setNested(key: string, name: string, value: unknown): void {
    const current = isRecord(this.#draft[key]) ? this.#draft[key] : {};
    this.#draft[key] = { ...current, [name]: value };
    this.#markDirty();
  }

  #startInput(kind: InputKind): void {
    this.#returnScreen = this.#screen;
    this.#inputKind = kind;
    this.#input = new Input();
    this.#input.prompt = "";
    this.#input.setValue(this.#inputValue(kind));
    this.#input.onSubmit = value => this.#applyInput(kind, value);
    this.#input.onEscape = () => {
      this.#input = undefined;
      this.#inputKind = undefined;
      this.#setScreen(this.#returnScreen);
    };
    this.#screen = "input";
    this.#cursor = 0;
    this.#scroll = 0;
    this.#status = "";
    this.#callbacks.requestRender();
  }

  #inputValue(kind: InputKind): string {
    if (["max_rows", "sentence_word_cap", "list_item_cap"].includes(kind)) return String(this.#numberValue(kind, 1));
    if (kind === "exempt_paths") {
      const paths = Array.isArray(this.#draft.exempt_paths) ? this.#draft.exempt_paths : [];
      return paths.map(item => sanitizeDisplay(item, 4096)).join(", ");
    }
    const mappings = isRecord(this.#draft.exempt_families) ? this.#draft.exempt_families : {};
    return Object.entries(mappings)
      .map(([pattern, families]) => `${sanitizeDisplay(pattern, 256)}=${Array.isArray(families) ? families.map(family => sanitizeDisplay(family, 128)).join(",") : ""}`)
      .join("; ");
  }

  #applyInput(kind: InputKind, value: string): void {
    const clean = value.replace(/[\u0000-\u001f\u007f]/g, " ").trim();
    if (["max_rows", "sentence_word_cap", "list_item_cap"].includes(kind)) {
      const parsed = Number(clean);
      if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > 10000) {
        this.#status = `${kind} must be an integer from 1 through 10000`;
        this.#callbacks.notify(this.#status, "warning");
        this.#callbacks.requestRender();
        return;
      }
      this.#draft[kind] = parsed;
      this.#finishInput(true);
      return;
    }
    if (kind === "exempt_paths") {
      const paths = clean
        ? clean.split(",").map(path => path.trim()).filter(Boolean)
        : [];
      if (paths.some(path => !safePolicyString(path))) {
        this.#status = "Exempt paths must be nonempty, control-free values";
        this.#callbacks.notify(this.#status, "warning");
        this.#callbacks.requestRender();
        return;
      }
      this.#draft.exempt_paths = paths;
      this.#finishInput(true);
      return;
    }
    const parsed = this.#parseFamilyExemptions(clean);
    if (!parsed) return;
    this.#draft.exempt_families = parsed;
    this.#finishInput(true);
  }

  #parseFamilyExemptions(value: string): Record<string, string[]> | undefined {
    if (!value) return {};
    const families = new Set(this.#state.families.map(family => family.name));
    const output: Record<string, string[]> = {};
    for (const entry of value.split(";")) {
      const separator = entry.indexOf("=");
      if (separator <= 0) {
        this.#status = "Use pattern=family1,family2 entries separated by semicolons";
        this.#callbacks.notify(this.#status, "warning");
        this.#callbacks.requestRender();
        return undefined;
      }
      const pattern = entry.slice(0, separator).trim();
      const selected = entry
        .slice(separator + 1)
        .split(",")
        .map(family => family.trim())
        .filter(Boolean);
      if (!safePolicyString(pattern) || selected.some(family => !families.has(family))) {
        this.#status = "Family exemptions must name supported families";
        this.#callbacks.notify(this.#status, "warning");
        this.#callbacks.requestRender();
        return undefined;
      }
      output[pattern] = selected;
    }
    return output;
  }

  #finishInput(changed: boolean): void {
    if (changed) this.#markDirty();
    this.#input = undefined;
    this.#inputKind = undefined;
    this.#setScreen(this.#returnScreen);
  }

  async #save(): Promise<void> {
    if (this.#saving) return;
    this.#saving = true;
    this.#status = "Saving policy...";
    this.#callbacks.requestRender();
    try {
      const saved = await this.#callbacks.save(this.#state.digest, copyValues(this.#draft));
      if (saved) {
        this.#state = saved;
        this.#draft = copyValues(saved.values);
      }
      this.#dirty = false;
      this.#saving = false;
      this.#callbacks.close("saved");
    } catch (error) {
      this.#saving = false;
      this.#status = sanitizeDisplay(error instanceof Error ? error.message : "ADW policy save failed", 240);
      this.#callbacks.notify(this.#status, "error");
      this.#callbacks.requestRender();
    }
  }
}
