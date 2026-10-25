import { describe, expect, it } from "vitest";

import {
  clearPending,
  newOperationId,
  pendingFor,
  savePending,
  type PendingOperation,
} from "./operationStore";

function freshStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => map.get(k) ?? null,
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, v),
  };
}

const PENDING_A: PendingOperation = {
  operationId: "op-uuid-a",
  accountReference: "ACC-001",
  periodStart: "2026-03-02",
  periodEnd: "2026-03-03",
  submittedAt: "2026-10-25T05:00:00Z",
};

const PENDING_B: PendingOperation = {
  ...PENDING_A,
  operationId: "op-uuid-b",
  accountReference: "ACC-002",
};

describe("newOperationId", () => {
  it("generates unique collision-resistant IDs across sessions", () => {
    // Two independent browser sessions (no shared counter) cannot collide.
    const ids = new Set(Array.from({ length: 500 }, () => newOperationId()));
    expect(ids.size).toBe(500);
  });
});

describe("pending operation persistence", () => {
  it("round-trips through storage for reload recovery", () => {
    const storage = freshStorage();
    savePending(storage, PENDING_A);
    // Simulated reload: a fresh module read sees the persisted intent.
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING_A);
  });

  it("resolves only for the same account and period", () => {
    const storage = freshStorage();
    savePending(storage, PENDING_A);
    expect(pendingFor(storage, "ACC-002", "2026-03-02", "2026-03-03")).toBeNull();
    expect(pendingFor(storage, "ACC-001", "2026-03-03", "2026-03-04")).toBeNull();
  });

  it("preserves independent intents for other accounts and periods", () => {
    const storage = freshStorage();
    savePending(storage, PENDING_A);
    // Billing a different account while A's result is still uncertain must
    // not overwrite A's identity — returning to A resumes the same op.
    savePending(storage, PENDING_B);
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING_A);
    expect(pendingFor(storage, "ACC-002", "2026-03-02", "2026-03-03")).toEqual(PENDING_B);
    // A different period under the same account is an independent intent.
    savePending(storage, { ...PENDING_A, operationId: "op-uuid-c", periodStart: "2026-03-03", periodEnd: "2026-03-04" });
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING_A);
  });

  it("clears only the matching operation, never a newer or unrelated one", () => {
    const storage = freshStorage();
    savePending(storage, PENDING_A);
    savePending(storage, PENDING_B);
    // A delayed terminal callback from another account clears only itself.
    clearPending(storage, PENDING_B.operationId);
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING_A);
    expect(pendingFor(storage, "ACC-002", "2026-03-02", "2026-03-03")).toBeNull();
    // A stale callback for an already-cleared op is a no-op.
    clearPending(storage, PENDING_B.operationId);
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING_A);
  });

  it("ignores corrupt payloads and clears cleanly", () => {
    const storage = freshStorage();
    storage.setItem("taryx.pendingOperation.ACC-001.2026-03-02.2026-03-03", "not-json{");
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toBeNull();
    savePending(storage, PENDING_A);
    clearPending(storage, PENDING_A.operationId);
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toBeNull();
  });
});
