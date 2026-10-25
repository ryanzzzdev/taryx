import { useCallback, useEffect, useRef, useState } from "react";

import {
  clearPending,
  newOperationId,
  pendingFor,
  savePending,
} from "./operationStore";

/* Operator portal — decision 004 contract.
 * Session auth + CSRF; mutations return {ok, code} payloads; billAccount
 * returns an operation ID polled via billingOperation. Retrying with the
 * same operation ID is the idempotent recovery path.
 */

type Me = { username: string; role: string | null };
type Account = { reference: string; name: string; channels: Channel[] };
type Channel = { id: number; suffix: string; direction: string };
type Batch = { status: string; acceptedCount: number; quarantinedCount: number; errorCode: string | null };
type Run = { id: number; total: string; inputDigest: string };
type Posting = { accountCode: string; debit: string; credit: string };
type Adjustment = { number: string; generation: number; deltaTotal: string };
type Invoice = {
  number: string;
  total: string;
  journalEntries: { postings: Posting[] }[];
  adjustments: Adjustment[];
};
type Operation = {
  operationId: string;
  status: string;
  detail: string | null;
  invoice: Invoice | null;
  adjustment: Adjustment | null;
};
type Quarantine = {
  id: number;
  intervalEndUtc: string;
  detail: string;
  channel: { suffix: string };
  candidateRecords: { id: number; value: string; quality: string }[];
};

type GqlError = { message: string; extensions?: { code?: string } };

function csrfToken(): string {
  const match = /csrftoken=([^;]+)/.exec(document.cookie);
  return match?.[1] ?? "";
}

/* CSRF bootstrap: the first request must be a safe GET — Django only
 * issues the csrftoken cookie on non-mutating responses, and POSTs are
 * rejected by CSRF middleware before the view runs. A 403 can also mean
 * the token rotated (e.g. after login), so we re-bootstrap and retry once.
 */
async function bootstrapCsrf(): Promise<void> {
  await fetch(`/graphql?query=${encodeURIComponent("{__typename}")}`, {
    credentials: "same-origin",
  });
}

async function gql<T>(query: string, variables?: Record<string, unknown>): Promise<T> {
  const post = () =>
    fetch("/graphql", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify({ query, variables }),
    });
  if (!csrfToken()) await bootstrapCsrf();
  let res = await post();
  if (res.status === 403) {
    await bootstrapCsrf();
    res = await post();
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  let body: { data?: T; errors?: GqlError[] };
  try {
    body = (await res.json()) as { data?: T; errors?: GqlError[] };
  } catch {
    throw new Error(`non-JSON response (HTTP ${res.status})`);
  }
  if (body.errors?.length) {
    const err = body.errors[0]!;
    throw new Error(err.extensions?.code ?? err.message);
  }
  if (!body.data) throw new Error("empty response");
  return body.data;
}

const mono: React.CSSProperties = { fontFamily: "ui-monospace, monospace" };
const card: React.CSSProperties = {
  border: "1px solid #ccc",
  borderRadius: 4,
  padding: "0.6rem 0.8rem",
  marginTop: "0.6rem",
};

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshMe = useCallback(() => {
    gql<{ me: Me | null }>("{me{username role}}")
      .then((d) => setMe(d.me))
      .catch(() => setMe(null));
  }, []);

  const refreshAccounts = useCallback(() => {
    gql<{ accounts: Account[] }>("{accounts{reference name channels{id suffix direction}}}")
      .then((d) => setAccounts(d.accounts))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refreshMe, [refreshMe]);
  useEffect(() => {
    if (me) refreshAccounts();
  }, [me, refreshAccounts]);

  if (me === undefined) return <main>…</main>;
  if (me === null) return <Login onLogin={refreshMe} />;
  const account = accounts.find((a) => a.reference === selected) ?? null;
  return (
    <main style={{ maxWidth: 880, margin: "0 auto", fontFamily: "system-ui" }}>
      <header style={{ display: "flex", justifyContent: "space-between" }}>
        <h1>Taryx operator portal</h1>
        <p>
          {me.username} ({me.role ?? "no role"}){" "}
          <button
            onClick={() =>
              gql("mutation{logout{ok}}").then(() => {
                setSelected(null);
                refreshMe();
              })
            }
          >
            Log out
          </button>
        </p>
      </header>
      {error && <p role="alert">Error: {error}</p>}
      <nav style={{ display: "flex", gap: "0.4rem" }}>
        {accounts.map((a) => (
          <button
            key={a.reference}
            onClick={() => setSelected(a.reference)}
            style={{ fontWeight: a.reference === selected ? "bold" : "normal" }}
          >
            {a.reference}
          </button>
        ))}
      </nav>
      {account ? (
        <AccountPanel
          account={account}
          role={me.role ?? ""}
          onError={setError}
        />
      ) : (
        <p>Select an account.</p>
      )}
      <QuarantinePanel role={me.role ?? ""} />
    </main>
  );
}

function Login({ onLogin }: { onLogin: () => void }) {
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <main style={{ maxWidth: 360, margin: "4rem auto", fontFamily: "system-ui" }}>
      <h1>Taryx sign in</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          gql<{ login: { ok: boolean; code: string | null } }>(
            "mutation($u:String!,$p:String!){login(username:$u,password:$p){ok code}}",
            { u: username, p: password },
          )
            .then((d) => (d.login.ok ? onLogin() : setError(d.login.code ?? "failed")))
            .catch((e: Error) => setError(e.message));
        }}
      >
        <label>
          User{" "}
          <select value={username} onChange={(e) => setUsername(e.target.value)}>
            <option>viewer</option>
            <option>operator</option>
            <option>approver</option>
          </select>
        </label>{" "}
        <label>
          Password{" "}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>{" "}
        <button type="submit">Sign in</button>
      </form>
      {error && <p role="alert">{error}</p>}
      <p style={mono}>dev identities: taryx-&lt;role&gt;</p>
    </main>
  );
}

function AccountPanel({
  account,
  role,
  onError,
}: {
  account: Account;
  role: string;
  onError: (m: string | null) => void;
}) {
  const [file, setFile] = useState({ name: "day1_base.nem12", content: "" });
  const [batch, setBatch] = useState<Batch | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [op, setOp] = useState<Operation | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const polledRef = useRef<string | null>(null);
  const canOperate = role === "operator";

  const period = { s: "2026-03-02", e: "2026-03-03" };

  const refreshInvoices = useCallback(() => {
    gql<{ invoices: Invoice[] }>(
      "query($r:String!){invoices(reference:$r){number total journalEntries{postings{accountCode debit credit}} adjustments{number generation deltaTotal}}}",
      { r: account.reference },
    ).then((d) => setInvoices(d.invoices));
  }, [account.reference]);

  const startPoll = useCallback(
    (operationId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      polledRef.current = operationId;
      pollRef.current = setInterval(() => {
        gql<{ billingOperation: Operation }>(
          "query($o:String!){billingOperation(operationId:$o){operationId status detail invoice{number total journalEntries{postings{accountCode debit credit}} adjustments{number generation deltaTotal}} adjustment{number deltaTotal}}}",
          { o: operationId },
        )
          .then((d) => {
            // Stale-response guard: only apply results for the operation
            // this panel is currently watching.
            if (d.billingOperation.operationId !== polledRef.current) return;
            setOp(d.billingOperation);
            if (d.billingOperation.status !== "PENDING") {
              if (pollRef.current) clearInterval(pollRef.current);
              clearPending(localStorage);
              refreshInvoices();
            }
          })
          .catch(() => undefined);
      }, 800);
    },
    [refreshInvoices],
  );

  useEffect(refreshInvoices, [refreshInvoices]);
  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );
  // Resume a persisted pending operation (reload recovery); reset display
  // state whenever the account changes so stale results can't bleed over.
  useEffect(() => {
    setOp(null);
    const pending = pendingFor(localStorage, account.reference, period.s, period.e);
    if (pending) {
      setOp({ operationId: pending.operationId, status: "PENDING", detail: null, invoice: null, adjustment: null });
      startPoll(pending.operationId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account.reference, startPoll]);

  const ingest = () => {
    setBusy(true);
    gql<{ ingestNem12: { ok: boolean; code: string | null; batch: Batch } }>(
      "mutation($f:String!,$c:String!){ingestNem12(filename:$f,content:$c){ok code batch{status acceptedCount quarantinedCount errorCode}}}",
      { f: file.name, c: file.content },
    )
      .then((d) => setBatch(d.ingestNem12.batch))
      .catch((e: Error) => onError(e.message))
      .finally(() => setBusy(false));
  };

  const rate = () => {
    setBusy(true);
    gql<{ rateAccount: { ok: boolean; code: string | null; message: string | null; run: Run | null } }>(
      "mutation($r:String!,$s:Date!,$e:Date!){rateAccount(reference:$r,periodStart:$s,periodEnd:$e){ok code message run{id total inputDigest}}}",
      { r: account.reference, s: period.s, e: period.e },
    )
      .then((d) => {
        const p = d.rateAccount;
        if (!p.ok) onError(`${p.code}: ${p.message}`);
        else setRun(p.run);
      })
      .catch((e: Error) => onError(e.message))
      .finally(() => setBusy(false));
  };

  const bill = (operationId: string) => {
    setBusy(true);
    gql<{ billAccount: { ok: boolean; code: string | null; message: string | null; operation: Operation | null } }>(
      "mutation($r:String!,$s:Date!,$e:Date!,$o:String!){billAccount(reference:$r,periodStart:$s,periodEnd:$e,operationId:$o){ok code message operation{operationId status}}}",
      { r: account.reference, s: period.s, e: period.e, o: operationId },
    )
      .then((d) => {
        const p = d.billAccount;
        if (!p.ok) {
          clearPending(localStorage); // terminal server-side refusal
          onError(`${p.code}: ${p.message}`);
        } else if (p.operation) {
          setOp(p.operation);
          startPoll(operationId);
        }
      })
      .catch((e: Error) => {
        // Uncertain outcome: keep the persisted ID — retrying or reloading
        // resumes the same operation rather than minting a fresh key.
        onError(`${e.message} — retry resumes operation ${operationId}`);
      })
      .finally(() => setBusy(false));
  };

  const newBill = () => {
    // Reuse the persisted intent when one exists: a lost response must be
    // recovered under the same operation ID, never a fresh key.
    const existing = pendingFor(localStorage, account.reference, period.s, period.e);
    const operationId = existing?.operationId ?? newOperationId();
    if (!existing) {
      savePending(localStorage, {
        operationId,
        accountReference: account.reference,
        periodStart: period.s,
        periodEnd: period.e,
        submittedAt: new Date().toISOString(),
      });
    }
    bill(operationId);
  };

  return (
    <section>
      <h2>
        {account.reference} — {account.name}
      </h2>
      <p style={mono}>
        channels: {account.channels.map((c) => `${c.suffix}(${c.direction})`).join(" ")} ·
        period {period.s} → {period.e}
      </p>
      <div style={card}>
        <strong>1 · Ingest NEM12</strong>
        <div>
          <input
            value={file.name}
            onChange={(e) => setFile({ ...file, name: e.target.value })}
            style={{ width: 220 }}
          />
          <textarea
            rows={3}
            style={{ width: "100%", ...mono }}
            placeholder="paste NEM12 content"
            value={file.content}
            onChange={(e) => setFile({ ...file, content: e.target.value })}
          />
          <button disabled={!canOperate || busy || !file.content} onClick={ingest}>
            Ingest
          </button>
          {batch && (
            <span style={mono}>
              {" "}
              → {batch.status} ({batch.acceptedCount} accepted
              {batch.quarantinedCount ? `, ${batch.quarantinedCount} quarantined` : ""}
              {batch.errorCode ? `, ${batch.errorCode}` : ""})
            </span>
          )}
        </div>
      </div>
      <div style={card}>
        <strong>2 · Rate</strong>{" "}
        <button disabled={!canOperate || busy} onClick={rate}>
          Rate period
        </button>
        {run && (
          <span style={mono}>
            {" "}
            → run {run.id} total ${run.total} digest {run.inputDigest.slice(0, 12)}…
          </span>
        )}
      </div>
      <div style={card}>
        <strong>3 · Bill / correct</strong>{" "}
        <button disabled={!canOperate || busy} onClick={newBill}>
          Bill period
        </button>
        {op && (
          <div style={mono}>
            op {op.operationId}: <strong>{op.status}</strong>
            {op.detail ? ` — ${op.detail}` : ""}
            {op.invoice &&
              ` · invoice ${op.invoice.number} $${op.invoice.total}`}
            {op.adjustment &&
              ` · adjustment ${op.adjustment.number} Δ$${op.adjustment.deltaTotal}`}
            {op.status === "PENDING" && " (polling…)"}
          </div>
        )}
      </div>
      <div style={card}>
        <strong>Issued documents</strong>
        {invoices.map((inv) => (
          <div key={inv.number} style={mono}>
            {inv.number} ${inv.total}
            {inv.journalEntries.map((j, i) => (
              <span key={i}>
                {" "}
                [
                {j.postings
                  .map((p) => `${p.accountCode} ${p.debit !== "0.00" ? `Dr${p.debit}` : `Cr${p.credit}`}`)
                  .join(" | ")}
                ]
              </span>
            ))}
            {inv.adjustments.map((a) => (
              <span key={a.number}>
                {" "}
                +{a.number}(gen{a.generation}) Δ${a.deltaTotal}
              </span>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function QuarantinePanel({ role }: { role: string }) {
  const [items, setItems] = useState<Quarantine[]>([]);
  const refresh = useCallback(() => {
    gql<{ quarantinedIntervals: Quarantine[] }>(
      "{quarantinedIntervals{id intervalEndUtc detail channel{suffix} candidateRecords{id value quality}}}",
    ).then((d) => setItems(d.quarantinedIntervals));
  }, []);
  useEffect(refresh, [refresh]);
  if (!items.length) return null;
  return (
    <section style={card}>
      <strong>Open quarantines ({items.length})</strong>
      {items.map((q) => (
        <div key={q.id} style={mono}>
          #{q.id} {q.channel.suffix} {q.intervalEndUtc}: {q.detail}
          {q.candidateRecords.map((r) => (
            <span key={r.id}>
              {" "}
              rec{r.id}={r.value}({r.quality})
              {role === "approver" && (
                <button
                  onClick={() =>
                    gql(
                      "mutation($q:Int!,$r:Int!){resolveQuarantine(quarantineId:$q,recordId:$r,reason:\"operator portal review\"){ok code}}",
                      { q: q.id, r: r.id },
                    ).then(refresh)
                  }
                >
                  select
                </button>
              )}
            </span>
          ))}
        </div>
      ))}
    </section>
  );
}
