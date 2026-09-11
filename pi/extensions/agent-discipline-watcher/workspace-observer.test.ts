import { afterEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, renameSync, rmSync, statSync, symlinkSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { WorkspaceObserver } from "./workspace-observer";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

function root(): string {
  const path = mkdtempSync(join(tmpdir(), "adw-snapshot-"));
  roots.push(path);
  return path;
}

test("detects same-size writes even when modification time is restored", () => {
  const cwd = root();
  const path = join(cwd, "file.md");
  writeFileSync(path, "Before.\n");
  const before = statSync(path);
  const observer = new WorkspaceObserver();
  observer.begin("session", cwd);
  writeFileSync(path, "After..\n");
  utimesSync(path, before.atime, before.mtime);
  expect(observer.collect("session").changed).toEqual([path]);
});

test("does not follow symlink targets or traverse excluded trees", () => {
  const cwd = root();
  const outside = root();
  symlinkSync(outside, join(cwd, "linked"));
  mkdirSync(join(cwd, "node_modules"));
  const observer = new WorkspaceObserver();
  observer.begin("session", cwd);
  writeFileSync(join(outside, "external.md"), "External content.\n");
  writeFileSync(join(cwd, "node_modules/dependency.js"), "export const value = 1;\n");
  expect(observer.collect("session")).toEqual({ changed: [], deleted: [], notices: [] });
});

test("retains changes between consecutive calls and keeps sessions separate", () => {
  const cwd = root();
  const second = root();
  const observer = new WorkspaceObserver();
  observer.begin("first", cwd);
  observer.begin("second", second);
  const path = join(cwd, "new.md");
  writeFileSync(path, "New content.\n");
  observer.begin("first", cwd);
  expect(observer.collect("first").changed).toEqual([path]);
  expect(observer.collect("second").changed).toEqual([]);
  observer.reset("first");
  expect(observer.collect("first").changed).toEqual([]);
});

test("does not call acknowledged external or excluded files deleted", () => {
  const cwd = root();
  const external = join(root(), "external.md");
  mkdirSync(join(cwd, "node_modules"));
  const excluded = join(cwd, "node_modules/local.md");
  writeFileSync(external, "External content.\n");
  writeFileSync(excluded, "Excluded content.\n");
  const observer = new WorkspaceObserver();
  observer.begin("session", cwd);
  observer.acknowledge("session", external);
  observer.acknowledge("session", excluded);
  symlinkSync(external, join(cwd, "linked.md"));
  observer.acknowledge("session", join(cwd, "linked.md"));
  symlinkSync(join(external, ".."), join(cwd, "linked-directory"));
  observer.acknowledge("session", join(cwd, "linked-directory/external.md"));
  expect(observer.collect("session").deleted).toEqual([]);
});

test("retains known files across incomplete snapshots", () => {
  const cwd = root();
  const path = join(cwd, "existing.md");
  writeFileSync(path, "Existing content.\n");
  const observer = new WorkspaceObserver();
  observer.begin("session", cwd);
  const moved = join(root(), "moved");
  renameSync(cwd, moved);
  expect(observer.collect("session").deleted).toEqual([]);
  renameSync(moved, cwd);
  expect(observer.collect("session").changed).toEqual([]);
});

test("does not infer writes from files absent in an incomplete initial snapshot", () => {
  const cwd = join(root(), "workspace");
  const observer = new WorkspaceObserver();
  observer.begin("session", cwd);
  mkdirSync(cwd);
  writeFileSync(join(cwd, "existing.md"), "Existing content.\n");
  expect(observer.collect("session").changed).toEqual([]);
});
