import { useEffect, useState, type ReactNode } from "react";

/* Operator manual + inline help.
 *
 * `HELP` maps a topic key to a short popover explanation plus the manual
 * section it belongs to. `Help` renders the `?` icon used next to section
 * titles and column headers; its link opens `#manual/<anchor>` in a new
 * tab, which App renders as a standalone manual page — no router needed.
 */

export type HelpTopic = { title: string; text: string; anchor: string };

export const HELP: Record<string, HelpTopic> = {
  "accounts-table": {
    title: "Accounts",
    text: "One row per customer account in this client's estate. Click a row to open its billing workspace below.",
    anchor: "accounts",
  },
  "col-reference": {
    title: "Reference",
    text: "The client's internal account number. References deliberately overlap between clients — same ID, different data.",
    anchor: "accounts",
  },
  "col-name": {
    title: "Name",
    text: "The (fictional) customer business name on the account.",
    anchor: "accounts",
  },
  "col-channels": {
    title: "Channels",
    text: "Meter registers on this account's NMI. E1 = import (consumption ↓), B1 = export (solar feed-in ↑).",
    anchor: "channels",
  },
  "col-docs": {
    title: "Docs",
    text: "How many documents (invoices + adjustments) have been issued for this account.",
    anchor: "documents",
  },
  "col-last-total": {
    title: "Last total",
    text: "Total including GST on the most recently issued document.",
    anchor: "documents",
  },
  "col-source": {
    title: "Source",
    text: "Which engine produced the latest document: 'new' (Taryx) or 'legacy' (the engine being migrated off).",
    anchor: "migration",
  },
  period: {
    title: "Period",
    text: "The billing window used by Rate and Bill. Dates are NEM days. Changing the period resets the workspace.",
    anchor: "pipeline",
  },
  "account-fields": {
    title: "Account summary",
    text: "This account's meter channels, the active billing period, issued document count, and your role.",
    anchor: "accounts",
  },
  ingest: {
    title: "Step 1 — Ingest NEM12",
    text: "Paste a raw NEM12 file. Records are parsed into interval data per channel. Conflicting revisions are quarantined, not silently overwritten.",
    anchor: "pipeline",
  },
  rate: {
    title: "Step 2 — Rate",
    text: "Run the pricing engine over accepted intervals: quantity × tariff + GST. Produces a pinned RatingRun — nothing is issued yet, so you can re-rate freely.",
    anchor: "pipeline",
  },
  bill: {
    title: "Step 3 — Bill / correct",
    text: "Creates a durable operation; a worker issues the invoice and a balanced journal. Re-billing after revised data appends an adjustment — the original invoice is never rewritten.",
    anchor: "pipeline",
  },
  documents: {
    title: "Issued documents",
    text: "The audit trail: itemised rating lines, balanced journal postings, and the document register with any adjustments.",
    anchor: "documents",
  },
  "col-tariff": {
    title: "Tariff",
    text: "The tariff code from the client's catalogue that priced this line.",
    anchor: "documents",
  },
  "col-element": {
    title: "Element",
    text: "What is being charged: energy consumption, solar feed-in credit, daily supply charge, etc.",
    anchor: "documents",
  },
  "col-band": {
    title: "Band",
    text: "Time-of-use band (e.g. peak/off-peak), or '—' for flat-rate lines.",
    anchor: "documents",
  },
  "col-qty": {
    title: "Qty",
    text: "Quantity billed — kWh for energy lines, days for supply charges.",
    anchor: "documents",
  },
  "col-rate": {
    title: "Rate",
    text: "Price per unit from the tariff, in dollars.",
    anchor: "documents",
  },
  "col-amount": {
    title: "Amount",
    text: "Line total before GST. Negative (purple) values are credits, e.g. solar export.",
    anchor: "documents",
  },
  "col-gst": {
    title: "GST",
    text: "Goods & services tax on this line at the client's configured rate.",
    anchor: "documents",
  },
  "col-basis": {
    title: "Basis",
    text: "The segment dates this line covers and why it exists (e.g. a mid-period tariff change splits the month).",
    anchor: "documents",
  },
  "journal-acct": {
    title: "Acct",
    text: "Ledger account code: receivables, revenue lines, GST payable.",
    anchor: "documents",
  },
  "journal-drcr": {
    title: "Dr / Cr",
    text: "Debit and credit legs. Every journal balances — total debits equal total credits.",
    anchor: "documents",
  },
  "reg-doc": {
    title: "Doc",
    text: "Document number. INV-* are original invoices; ADJ-* are appended adjustments. Click a row to view it.",
    anchor: "documents",
  },
  "reg-source": {
    title: "Source",
    text: "Which engine calculated this document — flips 'legacy' → 'new' after migration cutover.",
    anchor: "migration",
  },
  "reg-adj": {
    title: "Adjustments",
    text: "Corrections appended after revised meter data. Each carries a generation and a signed delta total.",
    anchor: "documents",
  },
  quarantine: {
    title: "Quarantine",
    text: "Intervals where a revised file conflicts with data already held. An approver picks the winning candidate record — nothing is auto-overwritten.",
    anchor: "quarantine",
  },
  migration: {
    title: "Migration cohorts",
    text: "Accounts being moved off the legacy engine. Shows routing mode, engine-vs-engine comparisons, itemised diffs, decisions, and gated transitions.",
    anchor: "migration",
  },
  events: {
    title: "Session events",
    text: "A local audit log of actions you took in this browser session — ingest, rate, bill operations, decisions, transitions.",
    anchor: "events",
  },
};

export function Help({ topic }: { topic: keyof typeof HELP }) {
  const [open, setOpen] = useState(false);
  const t = HELP[topic]!;
  return (
    <span className="helpwrap">
      <button
        type="button"
        className="helpbtn"
        aria-label={`About ${t.title}`}
        title={t.title}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        ?
      </button>
      {open && (
        <>
          <div className="helpbd" onClick={() => setOpen(false)} />
          <div className="helppop" role="tooltip">
            <b>{t.title}</b>
            <div>{t.text}</div>
            <a
              href={`#manual/${t.anchor}`}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
            >
              Manual ↗
            </a>
          </div>
        </>
      )}
    </span>
  );
}

/* ============ manual page ============ */

type Sub = { id: string; title: string };
type Section = { id: string; title: string; subs?: Sub[]; body: ReactNode };

const CODE = ({ children }: { children: ReactNode }) => (
  <code className="mono">{children}</code>
);

export const MANUAL: Section[] = [
  {
    id: "overview",
    title: "Overview — what this console is",
    body: (
      <>
        <p>
          The operator console is the back-office workspace for one Taryx
          client (retailer). The same build serves both fictional retailers —
          the badge in the top bar names which one you are connected to:
          Aurora Energy or Southgrid Retail. They share the codebase but not
          the data.
        </p>
        <p>Three areas on one screen:</p>
        <ul>
          <li>
            <b>Accounts &amp; Billing</b> (left) — pick an account, run the
            ingest → rate → bill pipeline, inspect issued documents.
          </li>
          <li>
            <b>Quarantine</b> (right) — meter data conflicts waiting for a
            human decision.
          </li>
          <li>
            <b>Migration</b> (right) — the safe cutover of accounts from the
            legacy billing engine to Taryx.
          </li>
        </ul>
        <h3>Roles</h3>
        <table>
          <tbody>
            <tr>
              <td>
                <CODE>viewer</CODE>
              </td>
              <td>read-only — can look, cannot change</td>
            </tr>
            <tr>
              <td>
                <CODE>operator</CODE>
              </td>
              <td>ingest, rate, bill, record migration decisions</td>
            </tr>
            <tr>
              <td>
                <CODE>approver</CODE>
              </td>
              <td>resolve quarantines, drive cohort transitions</td>
            </tr>
          </tbody>
        </table>
        <p>
          The two portals share one browser cookie jar when opened on the
          same hostname. If a tab shows <CODE>permission_denied</CODE> while
          still displaying your name, hard-reload and sign in again — or open
          the second client on a different hostname (
          <CODE>localhost</CODE> vs <CODE>127.0.0.1</CODE>).
        </p>
      </>
    ),
  },
  {
    id: "accounts",
    title: "Accounts table & account panel",
    body: (
      <>
        <p>
          The top table lists this client's accounts —{" "}
          <b>reference, name, channels, document count, last total, source</b>.
          Clicking a row opens the account panel below it.
        </p>
        <p>
          The panel has three parts: the <b>Account</b> summary (channels,
          period, documents, your role), the <b>billing pipeline</b>, and the{" "}
          <b>issued documents</b> register. The <b>Period</b> filter in the
          sub-header sets the billing window; changing it resets the
          workspace so a half-finished operation can't leak into another
          period.
        </p>
      </>
    ),
  },
  {
    id: "channels",
    title: "Meter channels — E1, B1",
    body: (
      <>
        <p>
          A meter measures several registers at once; in NEM12 each register
          is a <b>channel</b> named by a suffix:
        </p>
        <table>
          <tbody>
            <tr>
              <td>
                <CODE>E1</CODE>
              </td>
              <td>
                import — energy the customer consumes; billed per kWh (↓)
              </td>
            </tr>
            <tr>
              <td>
                <CODE>B1</CODE>
              </td>
              <td>
                export — solar fed back to the grid; credited per kWh (↑)
              </td>
            </tr>
          </tbody>
        </table>
        <p>
          One NMI can hold many channels (e.g. <CODE>E11/E12/E13</CODE> for
          peak/shoulder/off-peak). Ingest stores every interval under its
          channel; rating prices each direction separately — consumption as a
          charge, export as a credit.
        </p>
      </>
    ),
  },
  {
    id: "pipeline",
    title: "The billing pipeline",
    subs: [
      { id: "ingest", title: "1. Ingest" },
      { id: "rate", title: "2. Rate" },
      { id: "bill", title: "3. Bill / correct" },
    ],
    body: (
      <>
        <h3 id="sec-pipeline-ingest">1. Ingest</h3>
        <p>
          Paste a raw NEM12 file and submit. The file is parsed, intervals
          are stored under their channel, and the batch row reports{" "}
          <CODE>accepted</CODE>/<CODE>quarantined</CODE> counts. A later
          revision file replaces clean data but conflicting versions go to{" "}
          <b>quarantine</b> for an approver — nothing is silently
          overwritten.
        </p>
        <h3 id="sec-pipeline-rate">2. Rate</h3>
        <p>
          The pricing engine multiplies accepted intervals by the client's
          tariffs and GST, producing a <b>RatingRun</b>: a digest-stamped,
          itemised snapshot of every line (quantity, rate, amount, GST,
          basis). Rating is separate from billing — you can re-rate and
          compare, nothing reaches the ledger.
        </p>
        <h3 id="sec-pipeline-bill">3. Bill / correct</h3>
        <p>
          Creates a <b>durable operation</b> with a stable ID (persisted in
          the browser). A worker turns the latest RatingRun into an invoice
          plus a balanced journal — Dr receivables, Cr revenue, Cr GST.
          Reloading mid-flight resumes the same operation instead of
          double-billing; retrying with the same ID is idempotent.
        </p>
        <p>
          If meter data is revised after billing, re-billing the same period
          doesn't rewrite the invoice — it appends an <b>adjustment</b> (a
          signed delta document), keeping the original auditable. That is the
          "correct" half of the step.
        </p>
      </>
    ),
  },
  {
    id: "documents",
    title: "Issued documents",
    subs: [
      { id: "lines", title: "Rating lines" },
      { id: "journal", title: "Journal postings" },
      { id: "register", title: "Document register" },
    ],
    body: (
      <>
        <h3 id="sec-documents-lines">Rating lines</h3>
        <p>
          The itemised evidence behind the document: tariff, element, band,
          quantity, unit, rate, amount, GST, and the basis (segment dates +
          why the line exists). For legacy-source documents the pinned legacy
          response is shown in the same shape — the lines reconcile to the
          billed total.
        </p>
        <h3 id="sec-documents-journal">Journal postings</h3>
        <p>
          Double-entry legs for the document: account code, debit, credit.
          Every journal balances — debits equal credits.
        </p>
        <h3 id="sec-documents-register">Document register</h3>
        <p>
          Every document on the account: <CODE>INV-*</CODE> invoices and{" "}
          <CODE>ADJ-*</CODE> adjustments with generation and signed delta.
          Click a row to view it. The <b>Source</b> chip says which engine
          calculated the document (<CODE>legacy</CODE>/<CODE>new</CODE>).
        </p>
      </>
    ),
  },
  {
    id: "quarantine",
    title: "Quarantine — conflicting meter data",
    body: (
      <>
        <p>
          When a revised NEM12 file contains an interval that conflicts with
          data already held (different value, same timestamp), the interval
          is quarantined instead of overwritten. Each quarantine row shows
          the channel, the interval end, and the competing candidate records
          with their quality flags.
        </p>
        <p>
          An <CODE>approver</CODE> reviews the candidates and selects the
          winner; the decision is audited. Until resolved, quarantined
          intervals are excluded from rating.
        </p>
      </>
    ),
  },
  {
    id: "migration",
    title: "Migration — cohorts & cutover",
    subs: [
      { id: "modes", title: "Routing modes" },
      { id: "evidence", title: "Evidence & decisions" },
      { id: "transitions", title: "Transitions" },
    ],
    body: (
      <>
        <p>
          A <b>cohort</b> is a group of accounts being migrated off the
          legacy engine.
        </p>
        <h3 id="sec-migration-modes">Routing modes</h3>
        <p>
          Routing mode controls which engine's calculation is authoritative:
        </p>
        <table>
          <tbody>
            <tr>
              <td>
                <CODE>legacy_only</CODE>
              </td>
              <td>legacy engine still bills these accounts</td>
            </tr>
            <tr>
              <td>
                <CODE>shadow</CODE>
              </td>
              <td>
                new engine runs in parallel for evidence; legacy still bills
              </td>
            </tr>
            <tr>
              <td>
                <CODE>new_only</CODE>
              </td>
              <td>cut over — Taryx issues the documents</td>
            </tr>
          </tbody>
        </table>
        <h3 id="sec-migration-evidence">Evidence &amp; decisions</h3>
        <p>
          <b>Comparisons</b> run the same inputs through both engines and pin
          itemised <b>diffs</b> (e.g. a seeded legacy defect, or a deliberate
          client-policy difference). Each diff needs a decision:{" "}
          <CODE>preserve_client_policy</CODE> or{" "}
          <CODE>approved_defect_correction</CODE>. Re-generated evidence
          invalidates old decisions — they show as <i>stale</i> and need
          re-approval.
        </p>
        <h3 id="sec-migration-transitions">Transitions</h3>
        <p>
          <b>Start shadow → cut over → roll back</b> are approver-only,
          gated by blockers, optimistic-locked on a routing revision, and
          audited in cohort events.
        </p>
      </>
    ),
  },
  {
    id: "events",
    title: "Session events & operation recovery",
    body: (
      <>
        <p>
          The session-events card is a local audit log of your actions this
          session — ingests, runs, operations, decisions, transitions — with
          a status chip per entry.
        </p>
        <p>
          <b>Recovery:</b> when you click Bill, the operation ID is stored in
          the browser. Close or reload mid-flight and the portal resumes
          polling that same operation — it never mints a second billing
          request for the same intent.
        </p>
      </>
    ),
  },
];

export function ManualPage({
  section,
  clientName,
}: {
  section: string;
  clientName: string | null;
}) {
  useEffect(() => {
    const prev = document.title;
    document.title = `${clientName ?? "Taryx"} — Operator Manual`;
    return () => {
      document.title = prev;
    };
  }, [clientName]);

  useEffect(() => {
    const target = section ? document.getElementById(`sec-${section}`) : null;
    target?.scrollIntoView();
  }, [section]);

  return (
    <>
      <div className="masthead">
        <span className="logo">
          TARYX <em>Operator Manual</em>
        </span>
        {clientName && <span className="client">{clientName}</span>}
        <div className="right">
          <a href="#accounts" className="btn xs">
            ← Console
          </a>
        </div>
      </div>
      <div className="manual">
        <nav className="manual-nav">
          {MANUAL.map((s) => (
            <div key={s.id} className="mn-group">
              <a
                href={`#manual/${s.id}`}
                className={section === s.id ? "on" : ""}
              >
                {s.title}
              </a>
              {s.subs?.map((sub) => {
                const subId = `${s.id}-${sub.id}`;
                return (
                  <a
                    key={sub.id}
                    href={`#manual/${subId}`}
                    className={`sub${section === subId ? " on" : ""}`}
                  >
                    {sub.title}
                  </a>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="manual-body">
          <h1>Operator manual</h1>
          <p className="dim">
            What every part of the operator console means. The <b>?</b> icons
            throughout the console link back to the matching section here.
          </p>
          {MANUAL.map((s) => (
            <section key={s.id} id={`sec-${s.id}`}>
              <h2>{s.title}</h2>
              {s.body}
            </section>
          ))}
        </div>
      </div>
    </>
  );
}
