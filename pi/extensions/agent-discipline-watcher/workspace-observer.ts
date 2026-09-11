import { lstatSync, opendirSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

const MAX_ENTRIES = 20_000;
const MAX_SCAN_MS = 250;
const EXCLUDED = new Set([".git", "node_modules", ".adw"]);

type Snapshot = { files: Map<string, string>; complete: boolean };
type Session = { cwd: string; snapshot: Snapshot; warned: boolean };
export type ObservedChanges = { changed: string[]; deleted: string[]; notices: string[] };

function fingerprint(path: string): string | undefined {
  const stat = lstatSync(path, { bigint: true });
  return stat.isFile() ? [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs, stat.mode].join(":") : undefined;
}

function snapshot(cwd: string): Snapshot {
  const files = new Map<string, string>();
  const directories = [cwd];
  const deadline = performance.now() + MAX_SCAN_MS;
  let entries = 0;
  let complete = true;
  while (directories.length) {
    if (entries >= MAX_ENTRIES || performance.now() >= deadline) return { files, complete: false };
    const directory = directories.pop()!;
    try {
      const handle = opendirSync(directory);
      try {
        let entry;
        while ((entry = handle.readSync()) !== null) {
          if (++entries > MAX_ENTRIES || performance.now() >= deadline) return { files, complete: false };
          if (EXCLUDED.has(entry.name)) continue;
          const path = resolve(directory, entry.name);
          const stat = lstatSync(path, { bigint: true });
          if (stat.isDirectory()) directories.push(path);
          else if (stat.isFile()) files.set(path, [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs, stat.mode].join(":"));
        }
      } finally {
        handle.closeSync();
      }
    } catch {
      complete = false;
    }
  }
  return { files, complete };
}

export class WorkspaceObserver {
  private readonly sessions = new Map<string, Session>();

  reset(session: string): void {
    this.sessions.delete(session);
  }

  begin(session: string, cwd: string): void {
    const root = resolve(cwd);
    if (this.sessions.get(session)?.cwd === root) return;
    this.sessions.set(session, { cwd: root, snapshot: snapshot(root), warned: false });
  }

  acknowledge(session: string, path: string): void {
    const state = this.sessions.get(session);
    if (!state) return;
    const local = relative(state.cwd, path);
    if (isAbsolute(local) || local === ".." || local.startsWith(`..${sep}`) || local.split(sep).some(part => EXCLUDED.has(part))) return;
    if (!state.snapshot.files.has(path) && state.snapshot.files.size >= MAX_ENTRIES) return;
    try {
      let directory = state.cwd;
      for (const part of local.split(sep).slice(0, -1)) {
        directory = resolve(directory, part);
        if (lstatSync(directory).isSymbolicLink()) return;
      }
      const stamp = fingerprint(path);
      if (stamp !== undefined) state.snapshot.files.set(path, stamp);
    } catch {
      return;
    }
  }

  collect(session: string): ObservedChanges {
    const state = this.sessions.get(session);
    if (!state) return { changed: [], deleted: [], notices: [] };
    const current = snapshot(state.cwd);
    const previous = state.snapshot;
    const changed = [...current.files].filter(([path, stamp]) =>
      (previous.complete || previous.files.has(path)) && previous.files.get(path) !== stamp,
    ).map(([path]) => path);
    const deleted = current.complete ? [...state.snapshot.files.keys()].filter(path => !current.files.has(path)) : [];
    const notices: string[] = [];
    if ((!current.complete || !state.snapshot.complete) && !state.warned) {
      notices.push("ADW workspace observation was incomplete because a path could not be read or the scan limit was reached. JavaScript execution remains allowed.");
      state.warned = true;
    }
    if (!current.complete) {
      for (const [path, stamp] of previous.files) {
        if (current.files.size >= MAX_ENTRIES) break;
        if (!current.files.has(path)) current.files.set(path, stamp);
      }
    }
    state.snapshot = current;
    return { changed, deleted, notices };
  }
}
