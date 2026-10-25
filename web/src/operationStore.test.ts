import { describe, expect, it } from "vitest";

import {
  clearPending,
  loadPending,
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

const PENDING: PendingOperation = {
  operationId: "op-uuid-1",
  accountReference: "ACC-001",
  periodStart: "2026-03-02",
  periodEnd: "2026-03-03",
  submittedAt: "2026-10-25T05:00:00Z",
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
    savePending(storage, PENDING);
    // Simulated reload: a fresh module read sees the persisted intent.
    expect(loadPending(storage)).toEqual(PENDING);
    expect(loadPending(freshStorage())).toBeNull(); // other sessions unaffected
  });

  it("resolves only for the same account and period", () => {
    const storage = freshStorage();
    savePending(storage, PENDING);
    expect(pendingFor(storage, "ACC-001", "2026-03-02", "2026-03-03")).toEqual(PENDING);
    // Switching account or period must not replay the old operation.
    expect(pendingFor(storage, "ACC-002", "2026-03-02", "2026-03-03")).toBeNull();
    expect(pendingFor(storage, "ACC-001", "2026-03-03", "2026-03-04")).toBeNull();
  });

  it("ignores corrupt payloads and clears cleanly", () => {
    const storage = freshStorage();
    storage.setItem("taryx.pendingOperation", "not-json{");
    expect(loadPending(storage)).toBeNull();
    storage.setItem("taryx.pendingOperation", '{"operationId":1}');
    expect(loadPending(storage)).toBeNull();
    savePending(storage, PENDING);
    clearPending(storage);
    expect(loadPending(storage)).toBeNull();
  });
});
