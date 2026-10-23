import { expect, test } from "bun:test";
import { RULE_STATES } from "./adw-bridge";
import { AdwConfigOverlayComponent, decodeAdwPolicy } from "./adw-config";

type Values = Record<string, unknown>;

const RULE = "passive_voice";
const PER_SURFACE = { prose: "enforce", commit: "off" };
const DOWN = "\x1b[B";
const ENTER = "\r";
const ESCAPE = "\x1b";
const WIDTH = 120;
const SOURCES: Array<[string, Values]> = [
  ["set in the project config", { rule_gates: { [RULE]: PER_SURFACE } }],
  ["inherited from a wider config", {}],
];

const STRICTEST_STATES: Array<[string, Values, string]> = [
  ["enforce for prose and off for commit", { prose: "enforce", commit: "off" }, "enforce"],
  ["observe for prose and judged for commit", { prose: "observe", commit: "judged" }, "judged"],
  ["off for prose and observe for all", { prose: "off", all: "observe" }, "observe"],
  ["off for commit with prose left to the family gate", { commit: "off" }, "enforce"],
  ["off for all", { all: "off" }, "off"],
];

function bridgeRead(values: Values, gate: Values): Values {
  return {
    ok: true, operation: "read", project_path: "/project", config_path: "/project/.agent-discipline.json",
    digest: null, exists: true, values, effective: { rule_gates: { [RULE]: gate } },
    families: [], family_states: {},
    rules: [{ name: RULE, states: [...RULE_STATES], locked: false }],
    rule_states: { [RULE]: gate }, always_blocking_rules: [],
    runtime: { python: {}, embedding: {}, embedding_model: {} },
  };
}

function screenFor(values: Values, saves: Values[], gate: Values = PER_SURFACE): AdwConfigOverlayComponent {
  return new AdwConfigOverlayComponent({} as never, decodeAdwPolicy(bridgeRead(values, gate)), {
    close() {}, requestRender() {}, notify() {},
    save: async (_digest, saved) => { saves.push(saved); },
  });
}

// Because each screen opens on row one, the label offset is the step count.
function choose(screen: AdwConfigOverlayComponent, label: string): void {
  const lines = screen.render(WIDTH);
  const steps = lines.findIndex(line => line.includes(label)) - lines.findIndex(line => line.includes("> "));
  for (let step = 0; step < steps; step += 1) screen.handleInput(DOWN);
  screen.handleInput(ENTER);
}

function ruleDetail(screen: AdwConfigOverlayComponent): string {
  const row = screen.render(WIDTH).find(line => line.includes(RULE)) ?? "";
  return row.slice(row.indexOf(RULE) + RULE.length).replace(/\|\s*$/, "").trim();
}

test.each(SOURCES)("a per-surface rule gate %s shows its own state instead of a single state it does not hold", (_source, values) => {
  const screen = screenFor(values, []);
  choose(screen, "Per-rule gates");

  const detail = ruleDetail(screen);

  expect(detail).not.toBe("");
  expect(RULE_STATES).not.toContain(detail);
});

test.each(SOURCES)("one Enter on a per-surface rule gate %s shows the single state that Save then writes", (_source, values) => {
  const saves: Values[] = [];
  const screen = screenFor(values, saves);
  choose(screen, "Per-rule gates");

  screen.handleInput(ENTER);
  const shown = ruleDetail(screen);
  screen.handleInput(ESCAPE);
  choose(screen, "Save policy");

  expect(RULE_STATES).toContain(shown);
  expect(saves).toEqual([expect.objectContaining({ rule_gates: { [RULE]: shown } })]);
});

test.each(STRICTEST_STATES)("one Enter on a rule gate set to %s moves to the strictest state a surface sees", (_label, gate, strictest) => {
  const screen = screenFor({ rule_gates: { [RULE]: gate } }, [], gate);
  choose(screen, "Per-rule gates");

  screen.handleInput(ENTER);

  expect(ruleDetail(screen)).toBe(strictest);
});
