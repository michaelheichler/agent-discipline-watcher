const UNKNOWN_TARGET = "<unresolved-target>";
const MAX_REJECTED_TOOLS = 1024;

type SessionState = {
  pending: Map<string, string>;
  acceptedTools: Map<string, Set<string>>;
  deletedTargets: Map<string, Set<string>>;
  rejectedTools: Set<string>;
};

function stateFor(sessions: Map<string, SessionState>, session: string): SessionState {
  let state = sessions.get(session);
  if (!state) {
    state = { pending: new Map(), acceptedTools: new Map(), deletedTargets: new Map(), rejectedTools: new Set() };
    sessions.set(session, state);
  }
  return state;
}

export class VerificationLedger {
  static readonly UNKNOWN_TARGET = UNKNOWN_TARGET;

  readonly #sessions = new Map<string, SessionState>();

  acceptTool(
    session: string,
    toolCallId: string,
    targets: readonly string[] = [],
    deletedTargets: readonly string[] = [],
  ): void {
    if (!session || !toolCallId) return;
    const state = stateFor(this.#sessions, session);
    state.rejectedTools.delete(toolCallId);
    state.acceptedTools.set(toolCallId, new Set(targets.filter(Boolean)));
    state.deletedTargets.set(toolCallId, new Set(deletedTargets.filter(Boolean)));
  }

  rejectTool(session: string, toolCallId: string): void {
    if (!session || !toolCallId) return;
    const state = stateFor(this.#sessions, session);
    state.acceptedTools.delete(toolCallId);
    state.deletedTargets.delete(toolCallId);
    state.rejectedTools.delete(toolCallId);
    state.rejectedTools.add(toolCallId);
    if (state.rejectedTools.size > MAX_REJECTED_TOOLS) {
      const oldest = state.rejectedTools.values().next().value;
      if (oldest !== undefined) state.rejectedTools.delete(oldest);
    }
    this.#dropEmpty(session, state);
  }

  acceptedTool(session: string, toolCallId: string): boolean {
    return Boolean(toolCallId && this.#sessions.get(session)?.acceptedTools.has(toolCallId));
  }

  acceptedTargets(session: string, toolCallId: string): string[] {
    return [...(this.#sessions.get(session)?.acceptedTools.get(toolCallId) ?? [])];
  }

  acceptedDeletedTargets(session: string, toolCallId: string): string[] {
    return [...(this.#sessions.get(session)?.deletedTargets.get(toolCallId) ?? [])];
  }

  rejectedTool(session: string, toolCallId: string): boolean {
    return Boolean(toolCallId && this.#sessions.get(session)?.rejectedTools.has(toolCallId));
  }

  finishTool(session: string, toolCallId: string): void {
    if (!session || !toolCallId) return;
    const state = this.#sessions.get(session);
    if (!state) return;
    state.acceptedTools.delete(toolCallId);
    state.deletedTargets.delete(toolCallId);
    state.rejectedTools.delete(toolCallId);
    this.#dropEmpty(session, state);
  }

  markPending(session: string, target: string, reason = ""): void {
    if (!session) return;
    const state = stateFor(this.#sessions, session);
    const key = target || UNKNOWN_TARGET;
    const previous = state.pending.get(key) ?? "";
    state.pending.set(key, reason || previous);
  }

  markUnknown(session: string): void {
    this.markPending(session, UNKNOWN_TARGET);
  }

  clearTarget(session: string, target: string): void {
    if (!session || !target) return;
    const state = this.#sessions.get(session);
    if (!state) return;
    state.pending.delete(target);
    this.#dropEmpty(session, state);
  }

  pendingTargets(session: string): string[] {
    return [...(this.#sessions.get(session)?.pending.keys() ?? [])];
  }

  pendingReasons(session: string): string[] {
    return [...new Set(this.#sessions.get(session)?.pending.values() ?? [])].filter(Boolean);
  }

  hasPending(session: string): boolean {
    return this.pendingTargets(session).length > 0;
  }

  resetSession(session: string): void {
    this.#sessions.delete(session);
  }

  #dropEmpty(session: string, state: SessionState): void {
    if (state.pending.size === 0 && state.acceptedTools.size === 0 && state.deletedTargets.size === 0 && state.rejectedTools.size === 0) {
      this.#sessions.delete(session);
    }
  }
}
