/* Durable browser operation identities (decision 004 / R7).
 *
 * A billing click generates one collision-resistant operation ID and
 * persists the intent before submission. A lost response is recovered by
 * reusing that same ID (the server's idempotent retry path), and a page
 * reload resumes polling the persisted pending operation. Intents are
 * keyed by account + period, so an in-flight operation for one account
 * is never overwritten or cleared by work on another.
 */

export interface PendingOperation {
  operationId: string;
  accountReference: string;
  periodStart: string;
  periodEnd: string;
  submittedAt: string;
}

const PREFIX = "taryx.pendingOperation";

function keyFor(accountReference: string, periodStart: string, periodEnd: string): string {
  return `${PREFIX}.${accountReference}.${periodStart}.${periodEnd}`;
}

export function newOperationId(): string {
  return crypto.randomUUID();
}

function parse(raw: string | null): PendingOperation | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingOperation>;
    if (
      typeof parsed.operationId === "string" &&
      typeof parsed.accountReference === "string" &&
      typeof parsed.periodStart === "string" &&
      typeof parsed.periodEnd === "string" &&
      typeof parsed.submittedAt === "string"
    ) {
      return parsed as PendingOperation;
    }
  } catch {
    // corrupt payload: treated as absent
  }
  return null;
}

export function pendingFor(
  storage: Storage,
  accountReference: string,
  periodStart: string,
  periodEnd: string,
): PendingOperation | null {
  const pending = parse(storage.getItem(keyFor(accountReference, periodStart, periodEnd)));
  if (
    pending &&
    pending.accountReference === accountReference &&
    pending.periodStart === periodStart &&
    pending.periodEnd === periodEnd
  ) {
    return pending;
  }
  return null;
}

export function savePending(storage: Storage, operation: PendingOperation): void {
  storage.setItem(
    keyFor(operation.accountReference, operation.periodStart, operation.periodEnd),
    JSON.stringify(operation),
  );
}

/** Clear a pending intent only when the stored operation is the same one
 * that just finished — a delayed callback can never erase a newer or
 * unrelated identity. */
export function clearPending(storage: Storage, operationId: string): void {
  for (let i = storage.length - 1; i >= 0; i--) {
    const key = storage.key(i);
    if (key?.startsWith(`${PREFIX}.`)) {
      const pending = parse(storage.getItem(key));
      if (pending && pending.operationId === operationId) {
        storage.removeItem(key);
      }
    }
  }
}
