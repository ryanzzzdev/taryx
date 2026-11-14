import { useCallback, useEffect, useRef, useState } from "react";

import { Help, ManualPage } from "./manual";
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
 *
 * Presentation: design B "enterprise suite" (docs/design/) — masthead,
 * master-detail grid, status chips, theme tokens in theme.css.
 */

type Me = { username: string; role: string | null };
type Account = { reference: string; name: string; channels: Channel[] };
type Channel = { id: number; suffix: string; direction: string };
type Batch = {
  status: string;
  acceptedCount: number;
  quarantinedCount: number;
  errorCode: string | null;
};
type Run = { id: number; total: string; inputDigest: string };
type Posting = { accountCode: string; debit: string; credit: string };
type Adjustment = { number: string; generation: number; deltaTotal: string };
type RatingLine = {
  sequence: number;
  tariffCode: string;
  element: string;
  band: string | null;
  quantity: string;
  unit: string;
  rate: string;
  amount: string;
  gst: string;
  basis: string;
  segmentFrom: string;
  segmentTo: string;
};
type Invoice = {
  number: string;
  total: string;
  calculationSource: string;
  ratingRun: {
    id: number;
    inputDigest: string;
    engineVersion: string;
    policyIdentity: string;
    lines: RatingLine[];
  };
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

type Period = { s: string; e: string };
type Evt = { t: string; kind: "ok" | "op" | "warn" | "bad" | "sys"; msg: string };

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

/* ============ theme ============ */

const THEME_KEY = "taryx-demo-theme";
type Theme = "light" | "dark" | "auto";

function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
}

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(THEME_KEY);
    return stored === "light" || stored === "dark" || stored === "auto"
      ? stored
      : "auto";
  });
  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);
  return [theme, setTheme];
}

function ThemeSeg({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  return (
    <div className="seg">
      {(["light", "dark", "auto"] as const).map((t) => (
        <button
          key={t}
          className={theme === t ? "on" : ""}
          onClick={() => setTheme(t)}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

/* ============ presentation helpers ============ */

function chipClass(status: string): string {
  const s = status.toLowerCase();
  if (/ok|accept|complete|success|match|settled|published|registered|balanced/.test(s))
    return "c-ok";
  if (/pend|rated|shadow|draft|submit|reconcil|inconclusive|unbilled|legacy/.test(s))
    return "c-warn";
  if (/fail|error|reject|quarantine|conflict|differ|bad|block|stale/.test(s))
    return "c-bad";
  return "c-info";
}

const Chip = ({ status, label }: { status: string; label?: string }) => (
  <span className={`chip ${chipClass(status)}`}>{label ?? status}</span>
);

/* ============ App ============ */

export function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [clientName, setClientName] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [period, setPeriod] = useState<Period>({ s: "2026-03-02", e: "2026-03-03" });
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<Evt[]>([]);
  const [theme, setTheme] = useTheme();
  const [hash, setHash] = useState(window.location.hash);

  useEffect(() => {
    const onHash = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const logEvent = useCallback((kind: Evt["kind"], msg: string) => {
    setEvents((prev) =>
      [{ t: new Date().toISOString().slice(11, 19), kind, msg }, ...prev].slice(0, 40),
    );
  }, []);

  const refreshMe = useCallback(() => {
    gql<{ me: Me | null }>("{me{username role}}")
      .then((d) => setMe(d.me))
      .catch(() => setMe(null));
  }, []);

  const refreshAccounts = useCallback(() => {
    gql<{ accounts: Account[] }>(
      "{accounts{reference name channels{id suffix direction}}}",
    )
      .then((d) => setAccounts(d.accounts))
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(refreshMe, [refreshMe]);
  useEffect(() => {
    if (me) refreshAccounts();
  }, [me, refreshAccounts]);

  // Client identity is unauthenticated deployment config — fetched before
  // login so the login page and tab title can brand the instance.
  useEffect(() => {
    gql<{ clientName: string }>("{clientName}")
      .then((d) => setClientName(d.clientName))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    if (clientName) document.title = `${clientName} — Taryx Operator Console`;
  }, [clientName]);

  // The manual renders for any visitor — it carries no account data, so it
  // can be read before signing in (help links open it in a new tab).
  if (hash.startsWith("#manual"))
    return <ManualPage section={hash.slice(8)} clientName={clientName} />;

  if (me === undefined) return <main className="wrap dim">…</main>;
  if (me === null)
    return (
      <Login
        onLogin={refreshMe}
        theme={theme}
        setTheme={setTheme}
        clientName={clientName}
      />
    );
  const account = accounts.find((a) => a.reference === selected) ?? null;
  return (
    <>
      <div className="masthead">
        <span className="logo">
          TARYX <em>Operator Console</em>
        </span>
        {clientName && <span className="client">{clientName}</span>}
        <nav className="tabs">
          <a href="#accounts" className="on">
            Accounts &amp; Billing
          </a>
          <a href="#quarantine">Quarantine</a>
          <a href="#migration">Migration</a>
          <a href="#manual">Manual</a>
        </nav>
        <span className="env">dev</span>
        <div className="right">
          <ThemeSeg theme={theme} setTheme={setTheme} />
          <span className="user">
            <b>{me.username}</b> · {me.role ?? "no role"}
          </span>
          <button
            className="btn xs"
            onClick={() =>
              gql("mutation{logout{ok}}").then(() => {
                setSelected(null);
                refreshMe();
              })
            }
          >
            Sign out
          </button>
        </div>
      </div>

      <div className="subhead">
        <div className="wrap">
          <span className="crumb">
            Accounts &amp; Billing <span className="faint">›</span>{" "}
            <b>{account?.reference ?? "select an account"}</b>
          </span>
          <div className="filters">
            <label>
              Period <Help topic="period" />
            </label>
            <input
              type="text"
              value={period.s}
              size={10}
              onChange={(e) => setPeriod({ ...period, s: e.target.value })}
            />
            <span className="faint">→</span>
            <input
              type="text"
              value={period.e}
              size={10}
              onChange={(e) => setPeriod({ ...period, e: e.target.value })}
            />
          </div>
        </div>
      </div>

      <div className="wrap">
        {error && (
          <div className="alert" role="alert" style={{ marginTop: 10 }}>
            <b>ERROR</b> {error}
          </div>
        )}
        <div className="layout">
          <div className="col" id="accounts">
            <AccountsTable
              accounts={accounts}
              selected={selected}
              onSelect={setSelected}
            />
            {account ? (
              // Keying by account+period forces a clean remount on switch:
              // all scoped state (batch, run, operation) resets and the old
              // poll interval is destroyed with the component.
              <AccountPanel
                key={`${account.reference}:${period.s}:${period.e}`}
                account={account}
                period={period}
                role={me.role ?? ""}
                onError={setError}
                log={logEvent}
              />
            ) : (
              <div className="card">
                <div className="bd dim">Select an account row above.</div>
              </div>
            )}
          </div>
          <div className="col">
            <QuarantinePanel role={me.role ?? ""} log={logEvent} />
            <MigrationPanel role={me.role ?? ""} log={logEvent} />
            <AuditCard events={events} />
          </div>
        </div>
      </div>
    </>
  );
}

/* ============ login ============ */

function Login({
  onLogin,
  theme,
  setTheme,
  clientName,
}: {
  onLogin: () => void;
  theme: Theme;
  setTheme: (t: Theme) => void;
  clientName: string | null;
}) {
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <main className="login-page">
      <div className="login-corner">
        <ThemeSeg theme={theme} setTheme={setTheme} />
      </div>
      <div className="login-card">
        <div className="login-brand">
          <div className="logo">
            TARYX <em>Operator Console</em>
          </div>
          <div className="tag">
            Retail energy billing, financial ledger and safe migration platform.
          </div>
          {clientName && <div className="login-client">{clientName}</div>}
          <ul>
            <li>Explainable itemised bills</li>
            <li>Balanced sealed journals</li>
            <li>Shadow-engine cutover gates</li>
          </ul>
          <div className="foot">session auth · CSRF protected</div>
        </div>
        <form
          className="login-form"
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
          <h1>Sign in</h1>
          <div className="sub">Operator workstation</div>
          {error && (
            <div className="alert" role="alert">
              <b>DENIED</b> {error}
            </div>
          )}
          <label className="f">
            <span>User</span>
            <select value={username} onChange={(e) => setUsername(e.target.value)}>
              <option>viewer</option>
              <option>operator</option>
              <option>approver</option>
            </select>
          </label>
          <label className="f">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button className="signin" type="submit">
            Sign in
          </button>
          <div className="hint">
            dev identities: <b>viewer · operator · approver</b>
            <div className="roles">
              <span className="r">
                <b>viewer</b>read-only
              </span>
              <span className="r">
                <b>operator</b>ingest·rate·bill
              </span>
              <span className="r">
                <b>approver</b>quarantine·cutover
              </span>
            </div>
          </div>
        </form>
      </div>
      <footer className="login-foot">taryx operator portal · local dev</footer>
    </main>
  );
}

/* ============ master table ============ */

function AccountsTable({
  accounts,
  selected,
  onSelect,
}: {
  accounts: Account[];
  selected: string | null;
  onSelect: (r: string) => void;
}) {
  const [summaries, setSummaries] = useState<
    Record<string, { count: number; total: string | null; source: string | null }>
  >({});
  useEffect(() => {
    for (const a of accounts) {
      gql<{ invoices: { total: string; calculationSource: string }[] }>(
        "query($r:String!){invoices(reference:$r){total calculationSource}}",
        { r: a.reference },
      ).then((d) => {
        const last = d.invoices[d.invoices.length - 1];
        setSummaries((s) => ({
          ...s,
          [a.reference]: {
            count: d.invoices.length,
            total: last?.total ?? null,
            source: last?.calculationSource ?? null,
          },
        }));
      });
    }
  }, [accounts]);
  return (
    <div className="card">
      <table>
        <caption>
          Accounts — {accounts.length} records <Help topic="accounts-table" />
        </caption>
        <thead>
          <tr>
            <th>
              Reference <Help topic="col-reference" />
            </th>
            <th>
              Name <Help topic="col-name" />
            </th>
            <th>
              Channels <Help topic="col-channels" />
            </th>
            <th className="r">
              Docs <Help topic="col-docs" />
            </th>
            <th className="r">
              Last total <Help topic="col-last-total" />
            </th>
            <th>
              Source <Help topic="col-source" />
            </th>
          </tr>
        </thead>
        <tbody>
          {accounts.map((a) => {
            const sum = summaries[a.reference];
            return (
              <tr
                key={a.reference}
                className={`click${a.reference === selected ? " sel" : ""}`}
                onClick={() => onSelect(a.reference)}
              >
                <td className="mono">
                  <b>{a.reference}</b>
                </td>
                <td>{a.name}</td>
                <td className="mono">
                  {a.channels
                    .map((c) => `${c.suffix}${c.direction === "export" ? "↑" : "↓"}`)
                    .join(" ")}
                </td>
                <td className="r">{sum?.count ?? "—"}</td>
                <td className="r">{sum?.total ? `$${sum.total}` : "—"}</td>
                <td>
                  {sum?.source ? (
                    <Chip status={sum.source} />
                  ) : (
                    <span className="chip c-dim">unbilled</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ============ account detail ============ */

function AccountPanel({
  account,
  period,
  role,
  onError,
  log,
}: {
  account: Account;
  period: Period;
  role: string;
  onError: (m: string | null) => void;
  log: (kind: Evt["kind"], msg: string) => void;
}) {
  const [file, setFile] = useState({ name: "day1_base.nem12", content: "" });
  const [batch, setBatch] = useState<Batch | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [op, setOp] = useState<Operation | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [docNumber, setDocNumber] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const polledRef = useRef<string | null>(null);
  const canOperate = role === "operator";

  const refreshInvoices = useCallback(() => {
    gql<{ invoices: Invoice[] }>(
      "query($r:String!){invoices(reference:$r){number total calculationSource journalEntries{postings{accountCode debit credit}} adjustments{number generation deltaTotal} ratingRun{id inputDigest engineVersion policyIdentity lines{sequence tariffCode element band quantity unit rate amount gst basis segmentFrom segmentTo}}}}",
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
              clearPending(localStorage, d.billingOperation.operationId);
              refreshInvoices();
              log(
                d.billingOperation.status === "COMPLETE" ? "ok" : "bad",
                `op ${operationId.slice(0, 8)}… → ${d.billingOperation.status}` +
                  (d.billingOperation.invoice
                    ? ` · ${d.billingOperation.invoice.number}`
                    : "") +
                  (d.billingOperation.adjustment
                    ? ` · ${d.billingOperation.adjustment.number}`
                    : ""),
              );
            }
          })
          .catch(() => undefined);
      }, 800);
    },
    [refreshInvoices, log],
  );

  useEffect(refreshInvoices, [refreshInvoices]);
  useEffect(
    () => () => {
      if (pollRef.current) clearInterval(pollRef.current);
    },
    [],
  );
  // Resume a persisted pending operation on mount (reload recovery).
  // The component is keyed by account+period, so mount state is always fresh.
  useEffect(() => {
    const pending = pendingFor(localStorage, account.reference, period.s, period.e);
    if (pending) {
      setOp({
        operationId: pending.operationId,
        status: "PENDING",
        detail: null,
        invoice: null,
        adjustment: null,
      });
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
      .then((d) => {
        setBatch(d.ingestNem12.batch);
        const b = d.ingestNem12.batch;
        log(
          b.quarantinedCount ? "warn" : "ok",
          `ingest ${file.name} · ${b.status} · ${b.acceptedCount} accepted` +
            (b.quarantinedCount ? ` · ${b.quarantinedCount} quarantined` : ""),
        );
      })
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
        else {
          setRun(p.run);
          log("ok", `run #${p.run!.id} → $${p.run!.total} · ${account.reference}`);
        }
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
          clearPending(localStorage, operationId); // terminal server-side refusal
          onError(`${p.code}: ${p.message}`);
        } else if (p.operation) {
          setOp(p.operation);
          log("op", `billAccount · op ${operationId.slice(0, 8)}… key persisted`);
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

  const doc = invoices.find((i) => i.number === docNumber) ?? invoices.at(-1) ?? null;
  return (
    <div className="card">
      <div className="head">
        <div className="dhead">
          <h1>
            {account.reference} — {account.name}
          </h1>
          {doc && <Chip status={doc.calculationSource} label={doc.calculationSource} />}
        </div>
      </div>
      <div className="bd">
        <fieldset className="grp">
          <legend>
            Account <Help topic="account-fields" />
          </legend>
          <div className="props">
            <div className="p">
              <b>Channels</b>
              <span>
                {account.channels.map((c) => `${c.suffix} ${c.direction}`).join(" · ")}
              </span>
            </div>
            <div className="p">
              <b>Period</b>
              <span>
                {period.s} → {period.e}
              </span>
            </div>
            <div className="p">
              <b>Documents</b>
              <span>{invoices.length} issued</span>
            </div>
            <div className="p">
              <b>Role</b>
              <span>{role}</span>
            </div>
          </div>
        </fieldset>

        <fieldset className="grp">
          <legend>
            Billing pipeline — {period.s} → {period.e}
          </legend>
          <div className="pipe">
            <div className="step">
              <div className="sh">
                <span className="n">1</span>Ingest NEM12
                <Help topic="ingest" />
                {batch && <Chip status={batch.status} />}
              </div>
              <div className="sb">
                <input
                  type="text"
                  value={file.name}
                  onChange={(e) => setFile({ ...file, name: e.target.value })}
                />
                <textarea
                  spellCheck={false}
                  placeholder="paste NEM12 content"
                  value={file.content}
                  onChange={(e) => setFile({ ...file, content: e.target.value })}
                />
                {batch &&
                  `${batch.acceptedCount} accepted` +
                    (batch.quarantinedCount
                      ? ` · ${batch.quarantinedCount} quarantined`
                      : "") +
                    (batch.errorCode ? ` · ${batch.errorCode}` : "")}
              </div>
              <div className="sf">
                <button
                  className="btn primary xs"
                  disabled={!canOperate || busy || !file.content}
                  onClick={ingest}
                >
                  Ingest
                </button>
              </div>
            </div>
            <div className="step">
              <div className="sh">
                <span className="n">2</span>Rate
                <Help topic="rate" />
                {run && <Chip status="ok" label={`run #${run.id}`} />}
              </div>
              <div className="sb">
                {run ? (
                  <>
                    total <b>${run.total}</b> incl GST
                    <br />
                    digest {run.inputDigest.slice(0, 12)}…
                  </>
                ) : (
                  "no run this session"
                )}
              </div>
              <div className="sf">
                <button className="btn xs" disabled={!canOperate || busy} onClick={rate}>
                  Rate period
                </button>
              </div>
            </div>
            <div className="step">
              <div className="sh">
                <span className="n">3</span>Bill / correct
                <Help topic="bill" />
                {op && <Chip status={op.status} />}
              </div>
              <div className="sb">
                {op ? (
                  <>
                    op {op.operationId.slice(0, 8)}… {op.status === "PENDING" && "polling…"}
                    {op.detail ? ` — ${op.detail}` : ""}
                    <br />
                    {op.invoice && (
                      <>
                        → <b>{op.invoice.number}</b> ${op.invoice.total}
                        <br />
                      </>
                    )}
                    {op.adjustment && (
                      <>
                        → <b>{op.adjustment.number}</b> Δ${op.adjustment.deltaTotal}
                      </>
                    )}
                  </>
                ) : (
                  "no operation this session"
                )}
              </div>
              <div className="sf">
                <button className="btn xs" disabled={!canOperate || busy} onClick={newBill}>
                  Bill period
                </button>
              </div>
            </div>
          </div>
        </fieldset>

        <fieldset className="grp" style={{ marginBottom: 0 }}>
          <legend>
            Issued documents <Help topic="documents" />
          </legend>
          {doc ? (
            <div className="split">
              <div>
                <div className="mini-cap">
                  {doc.number} — rating lines · run #{doc.ratingRun.id} · digest{" "}
                  {doc.ratingRun.inputDigest.slice(0, 8)}…
                </div>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>
                        Tariff <Help topic="col-tariff" />
                      </th>
                      <th>
                        Element <Help topic="col-element" />
                      </th>
                      <th>
                        Band <Help topic="col-band" />
                      </th>
                      <th className="r">
                        Qty <Help topic="col-qty" />
                      </th>
                      <th>Unit</th>
                      <th className="r">
                        Rate <Help topic="col-rate" />
                      </th>
                      <th className="r">
                        Amount <Help topic="col-amount" />
                      </th>
                      <th className="r">
                        GST <Help topic="col-gst" />
                      </th>
                      <th>
                        Basis <Help topic="col-basis" />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {doc.ratingRun.lines.map((l) => (
                      <tr key={l.sequence}>
                        <td className="mono">{l.sequence}</td>
                        <td className="mono">{l.tariffCode}</td>
                        <td>{l.element}</td>
                        <td className="mono faint">{l.band ?? "—"}</td>
                        <td className="r">{l.quantity}</td>
                        <td className="mono">{l.unit}</td>
                        <td className="r">{l.rate}</td>
                        <td className={`r${Number(l.amount) < 0 ? " neg" : ""}`}>
                          {l.amount}
                        </td>
                        <td className="r">{l.gst}</td>
                        <td className="faint" style={{ fontSize: "var(--fs-xs)" }}>
                          {l.segmentFrom}→{l.segmentTo} · {l.basis}
                        </td>
                      </tr>
                    ))}
                    <tr className="total">
                      <td colSpan={7}>
                        {doc.number} · engine {doc.ratingRun.engineVersion} · policy{" "}
                        {doc.ratingRun.policyIdentity}
                      </td>
                      <td className="r">{doc.total}</td>
                      <td className="r"></td>
                      <td></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div>
                {doc.journalEntries.map((j, i) => (
                  <div key={i}>
                    <div className="mini-cap">Journal {i + 1} — postings</div>
                    <table>
                      <thead>
                        <tr>
                          <th>
                            Acct <Help topic="journal-acct" />
                          </th>
                          <th className="r">
                            Dr <Help topic="journal-drcr" />
                          </th>
                          <th className="r">Cr</th>
                        </tr>
                      </thead>
                      <tbody>
                        {j.postings.map((p, k) => (
                          <tr key={k}>
                            <td className="mono">{p.accountCode}</td>
                            <td className="r">{p.debit !== "0.00" ? p.debit : ""}</td>
                            <td className="r">{p.credit !== "0.00" ? p.credit : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
                <div className="mini-cap">Document register</div>
                <table>
                  <thead>
                    <tr>
                      <th>
                        Doc <Help topic="reg-doc" />
                      </th>
                      <th className="r">Total</th>
                      <th>
                        Source <Help topic="reg-source" />
                      </th>
                      <th>
                        Adj. <Help topic="reg-adj" />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {invoices.map((inv) => (
                      <tr
                        key={inv.number}
                        className={`click${inv.number === doc.number ? " sel" : ""}`}
                        onClick={() => setDocNumber(inv.number)}
                      >
                        <td className="mono">{inv.number}</td>
                        <td className="r">
                          <b>{inv.total}</b>
                        </td>
                        <td>
                          <Chip status={inv.calculationSource} />
                        </td>
                        <td className="mono">
                          {inv.adjustments.length
                            ? inv.adjustments.map((a) => (
                                <span key={a.number}>
                                  {a.number} gen{a.generation}{" "}
                                  <span className="neg">Δ{a.deltaTotal}</span>{" "}
                                </span>
                              ))
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="dim" style={{ padding: "4px 2px" }}>
              No documents issued for {account.reference} yet.
            </div>
          )}
        </fieldset>
      </div>
    </div>
  );
}

/* ============ quarantine card ============ */

function QuarantinePanel({
  role,
  log,
}: {
  role: string;
  log: (kind: Evt["kind"], msg: string) => void;
}) {
  const [items, setItems] = useState<Quarantine[]>([]);
  const refresh = useCallback(() => {
    gql<{ quarantinedIntervals: Quarantine[] }>(
      "{quarantinedIntervals{id intervalEndUtc detail channel{suffix} candidateRecords{id value quality}}}",
    ).then((d) => setItems(d.quarantinedIntervals));
  }, []);
  useEffect(refresh, [refresh]);
  return (
    <div className="card" id="quarantine">
      <div className="head">
        <h2>
          Open quarantines <Help topic="quarantine" />
        </h2>
        <div className="tools">
          <Chip status={items.length ? "warn" : "ok"} label={`${items.length} open`} />
        </div>
      </div>
      <div className="bd">
        {items.length === 0 && <div className="dim">No open quarantined intervals.</div>}
        {items.map((q) => (
          <div key={q.id} className="qitem">
            <div className="qh">
              <span className="mono">
                #{q.id} · {q.channel.suffix}
              </span>
              <span className="faint mono">{q.intervalEndUtc.slice(0, 16)}</span>
              <span className="chip c-warn" style={{ marginLeft: "auto" }}>
                conflict
              </span>
            </div>
            <div className="qb">{q.detail}</div>
            {q.candidateRecords.map((r) => (
              <div key={r.id} className="cand">
                <span>rec{r.id}</span>
                <b>{r.value}</b>
                <Chip status={r.quality === "A" ? "ok" : "dim"} label={r.quality} />
                {role === "approver" && (
                  <button
                    className="btn xs"
                    style={{ marginLeft: "auto" }}
                    onClick={() =>
                      gql(
                        "mutation($q:Int!,$r:Int!){resolveQuarantine(quarantineId:$q,recordId:$r,reason:\"operator portal review\"){ok code}}",
                        { q: q.id, r: r.id },
                      )
                        .then(() => {
                          log("ok", `quarantine #${q.id} resolved → rec${r.id}`);
                          refresh();
                        })
                    }
                  >
                    select
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ============ migration card ============ */

/* Migration panel — cohorts, comparison evidence, scoped decisions and
 * guarded transitions (TAR-012). */
type Diff = {
  fingerprint: string;
  element: string;
  band: string | null;
  segment: [string, string];
  field: string;
  new: string;
  legacy: string;
  detail: string;
};
type Comparison = {
  id: number;
  account: { reference: string };
  periodStart: string;
  periodEnd: string;
  status: string;
  failureCode: string | null;
  snapshotHash: string;
  newEngineVersion: string;
  legacyVersionToken: string;
  createdAt: string;
  report: string; // JSONString — parsed at render
};
type Decision = {
  fingerprint: string;
  classification: string;
  actor: string | null;
  reason: string;
  valid: boolean;
};
type Cohort = {
  id: number;
  name: string;
  routingMode: string;
  routingRevision: number;
  evalPeriodStart: string;
  evalPeriodEnd: string;
  blockers: string[];
  members: { reference: string }[];
  decisions: Decision[];
};

const MODE_LABEL: Record<string, string> = {
  LEGACY_ONLY: "legacy only",
  SHADOW: "shadow",
  NEW_ONLY: "new only",
};

function MigrationPanel({
  role,
  log,
}: {
  role: string;
  log: (kind: Evt["kind"], msg: string) => void;
}) {
  const [cohorts, setCohorts] = useState<Cohort[]>([]);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const refresh = useCallback(() => {
    gql<{ cohorts: Cohort[] }>(
      `{cohorts{id name routingMode routingRevision evalPeriodStart evalPeriodEnd
        blockers members{reference} decisions{fingerprint classification actor reason valid}}}`,
    ).then((d) => setCohorts(d.cohorts));
    gql<{ comparisons: Comparison[] }>(
      `{comparisons{id account{reference} periodStart periodEnd status failureCode
        snapshotHash newEngineVersion legacyVersionToken createdAt report}}`,
    ).then((d) => setComparisons(d.comparisons));
  }, []);
  useEffect(refresh, [refresh]);

  const canDecide = role === "operator" || role === "approver";
  const canTransition = role === "approver";

  const transition = (c: Cohort, toMode: string, reason: string) =>
    gql<{ transitionCohort: { ok: boolean; code: string | null; message: string | null; cohort: { routingMode: string } | null } }>(
      `mutation($c:Int!,$m:String!,$r:Int!,$reason:String){
        transitionCohort(cohortId:$c,toMode:$m,expectedRevision:$r,reason:$reason){
          ok code message cohort{routingMode routingRevision}}}`,
      { c: c.id, m: toMode, r: c.routingRevision, reason },
    )
      .then((d) => {
        if (d.transitionCohort.ok) {
          setMsg(`${c.name} → ${d.transitionCohort.cohort!.routingMode}`);
          log("ok", `${c.name} → ${MODE_LABEL[d.transitionCohort.cohort!.routingMode]}`);
        } else {
          setMsg(`blocked: ${d.transitionCohort.code} — ${d.transitionCohort.message ?? ""}`);
          log("warn", `transition blocked: ${d.transitionCohort.code}`);
        }
      })
      .catch((e: Error) => setMsg(e.message))
      .finally(refresh);

  const decide = (c: Cohort, d: Diff, classification: string) => {
    const reason = window.prompt(`Reason for ${classification}:`) ?? "";
    if (!reason) return;
    gql<{ decideDiscrepancy: { ok: boolean; code: string | null; message: string | null } }>(
      `mutation($c:Int!,$f:String!,$cl:String!,$r:String!){
        decideDiscrepancy(cohortId:$c,fingerprint:$f,classification:$cl,reason:$r){
          ok code message}}`,
      { c: c.id, f: d.fingerprint, cl: classification, r: reason },
    )
      .then((r) => {
        setMsg(
          r.decideDiscrepancy.ok
            ? `decision recorded (${classification})`
            : `decision failed: ${r.decideDiscrepancy.code}`,
        );
        if (r.decideDiscrepancy.ok)
          log("op", `decision ${classification} · fp ${d.fingerprint.slice(0, 8)}…`);
      })
      .finally(refresh);
  };

  return (
    <div className="card" id="migration">
      <div className="head">
        <h2>
          Migration cohorts <Help topic="migration" />
        </h2>
        <div className="tools">
          {cohorts.map((c) => (
            <Chip
              key={c.id}
              status={c.routingMode}
              label={`${MODE_LABEL[c.routingMode] ?? c.routingMode} r${c.routingRevision}`}
            />
          ))}
        </div>
      </div>
      <div className="bd">
        {msg && <div className="mono dim">{msg}</div>}
        {cohorts.length === 0 && <div className="dim">No cohorts seeded.</div>}
        {cohorts.map((c) => {
          const decisions = new Map(c.decisions.map((d) => [d.fingerprint, d]));
          const members = new Set(c.members.map((m) => m.reference));
          const evidence = comparisons
            .filter(
              (row) =>
                members.has(row.account.reference) &&
                row.periodStart >= c.evalPeriodStart &&
                row.periodEnd <= c.evalPeriodEnd,
            )
            .map((row) => ({
              ...row,
              parsed: JSON.parse(row.report) as { diffs: Diff[] },
            }));
          return (
            <div key={c.id}>
              <div className="props" style={{ gridTemplateColumns: "1fr 1fr" }}>
                <div className="p">
                  <b>Cohort</b>
                  <span>{c.name}</span>
                </div>
                <div className="p">
                  <b>Mode</b>
                  <span>
                    {MODE_LABEL[c.routingMode] ?? c.routingMode} r{c.routingRevision}
                  </span>
                </div>
                <div className="p">
                  <b>Eval</b>
                  <span>
                    {c.evalPeriodStart} → {c.evalPeriodEnd}
                  </span>
                </div>
                <div className="p">
                  <b>Members</b>
                  <span>{c.members.map((m) => m.reference).join(", ")}</span>
                </div>
              </div>
              {c.blockers.length > 0 && (
                <div className="diffbox">
                  <div className="dh">
                    <span className="chip c-bad">gate blocked</span>
                    <span className="mono" style={{ fontSize: "var(--fs-xs)" }}>
                      {c.blockers.join(" · ")}
                    </span>
                  </div>
                </div>
              )}
              {evidence.map((row) => (
                <div key={row.id} className="diffbox">
                  <div className="dh">
                    <b className="mono">cmp#{row.id}</b>
                    <span className="mono">{row.account.reference}</span>
                    <Chip status={row.status} />
                    {row.failureCode && (
                      <span className="chip c-bad">{row.failureCode}</span>
                    )}
                  </div>
                  <div className="db">
                    new={row.newEngineVersion} legacy={row.legacyVersionToken} ·{" "}
                    {row.createdAt.slice(0, 19)}
                  </div>
                  {row.parsed.diffs?.map((d) => {
                    const dec = decisions.get(d.fingerprint);
                    return (
                      <div key={d.fingerprint} className="db">
                        {d.element}
                        {d.band ? `/${d.band}` : ""}.{d.field}: new <b>{d.new}</b> ≠
                        legacy <b>{d.legacy}</b>
                        {dec?.valid ? (
                          <span className="chip c-ok" style={{ marginLeft: 6 }}>
                            {dec.classification}
                          </span>
                        ) : (
                          <>
                            {dec && (
                              <span className="chip c-bad" style={{ marginLeft: 6 }}>
                                stale decision
                              </span>
                            )}
                            {canDecide && (
                              <span style={{ display: "inline-flex", gap: 4, marginLeft: 6 }}>
                                <button
                                  className="btn xs"
                                  onClick={() => decide(c, d, "preserve_client_policy")}
                                >
                                  preserve policy
                                </button>
                                <button
                                  className="btn xs"
                                  onClick={() =>
                                    decide(c, d, "approved_defect_correction")
                                  }
                                >
                                  approve correction
                                </button>
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              ))}
              {canTransition && (
                <div style={{ display: "flex", gap: 5, margin: "6px 0" }}>
                  {c.routingMode === "LEGACY_ONLY" && (
                    <button
                      className="btn xs"
                      onClick={() => transition(c, "shadow", "start shadow")}
                    >
                      Start shadow
                    </button>
                  )}
                  {c.routingMode !== "NEW_ONLY" && (
                    <button
                      className="btn primary xs"
                      onClick={() => transition(c, "new_only", "cut over")}
                    >
                      Cut over to new
                    </button>
                  )}
                  {c.routingMode !== "LEGACY_ONLY" && (
                    <button
                      className="btn xs"
                      onClick={() => transition(c, "legacy_only", "rollback routing")}
                    >
                      Roll back
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ============ session audit trail ============ */

function AuditCard({ events }: { events: Evt[] }) {
  const chip: Record<Evt["kind"], string> = {
    ok: "c-ok",
    op: "c-info",
    warn: "c-warn",
    bad: "c-bad",
    sys: "c-dim",
  };
  return (
    <div className="card">
      <div className="head">
        <h2>
          Session events <Help topic="events" />
        </h2>
        <div className="tools">
          <span className="chip c-dim">{events.length}</span>
        </div>
      </div>
      <div className="bd">
        {events.length === 0 && <div className="dim">Actions this session appear here.</div>}
        <table className="audit">
          <tbody>
            {events.map((e, i) => (
              <tr key={i}>
                <td className="t">{e.t}</td>
                <td>
                  <span className={`chip ${chip[e.kind]}`}>{e.kind}</span>
                </td>
                <td>{e.msg}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
