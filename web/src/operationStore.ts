/* Durable browser operation identities (decision 004 / R7).
 *
 * A billing click generates one collision-resistant operation ID and
 * persists the intent before submission. A lost response is recovered by
 * reusing that same ID (the server's idempotent retry path), and a page
 * reload resumes polling the persisted pending operation. State is
 * scoped to the account + period it was admitted for, so switching
 * accounts never replays or misattributes an operation.
 */

export interface PendingOperation {
  operationId: string;
  accountReference: string;
  periodStart: string;
  periodEnd: string;
  submittedAt: string;
}

const KEY = "taryx.pendingOperation";

export function newOperationId(): string {
  return crypto.randomUUID();
}

export function loadPending(storage: Storage): PendingOperation | null {
  const raw = storage.getItem(KEY);
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
  const pending = loadPending(storage);
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
  storage.setItem(KEY, JSON.stringify(operation));
}

export function clearPending(storage: Storage): void {
  storage.removeItem(KEY);
}
