# Independent M1 foundation re-review

Reviewed SHA: `c88b722f30526d8c57aef7ff89634ecd8a1fa983`
Date: 2026-11-08
Verdict: **CHANGES_REQUESTED**

## Scope and repository state

This review uses the user's M1 label for durable admission/outbox, atomic issuance, immutable invoices/journals, database balance enforcement and the operator journey. The canonical roadmap calls this scope **M2**, principally TAR-007–009; its original metering/bootstrap M1 is not renumbered or reopened. The candidate commit itself updates review-process documentation; this is a review of the implementation present at that full SHA, not only its commit diff.

HEAD matched the candidate. Pre-existing changes to `verdict.schema.json` and untracked `m1-events-r1.jsonl` / `m1-session-bootstrap.md` were preserved. No implementation changes or commits were made.

## Findings

### F1 — Medium: Empty journal headers bypass the database balance invariant

Location: `src/taryx/core/billing/migrations/0002_financial_integrity.py:44` (posting-only deferred trigger); `JournalEntry` creation.

The deferred check is scheduled only when a posting changes. Creating a journal header without any postings commits successfully, despite the documented minimum of two balanced postings. The journal then seals at commit and cannot receive its missing legs. This leaves an immutable, permanently incomplete financial journal. It also means an issuing path that accidentally omits all legs can evade the claimed database guard.

The independent probe creates a journal for an issued invoice inside a real committed transaction and expects an IntegrityError. PostgreSQL accepts it. Add a deferred check on journal creation as well as posting changes, inspecting the final posting set; preserve valid multi-leg transactions and explicitly decide any zero-value journal policy. Owner: TAR-007. This is the empty-journal case requested by historical M2 R4 but absent from its remediation tests.

### F2 — High: A failing outbox event prevents later independent recovery

Location: `src/taryx/core/billing/services.py:437–450`.

The drain selects oldest pending events and processes them in a list comprehension. Any calculation/service exception aborts the drain before later events run. The failing event stays pending and is selected first again on every invocation. After lost task delivery or a broker outage, one unavailable legacy calculation can therefore indefinitely prevent healthy new-engine billing from recovering, even though its inputs and calculator are available. Durable storage alone does not provide recovery progress.

The independent probe admits an unavailable legacy operation followed by a healthy new-engine operation. Two drains both encounter the same synthetic CalculationUnavailable; the healthy operation remains pending. Isolate failures per event and retain observable retry state; ensure a full batch of failing older events cannot permanently starve later work (for example with bounded retry scheduling). Do not mark unsuccessful work delivered. Owner: TAR-007; recovery campaign follow-up TAR-016.

### F3 — Medium: The operator cannot inspect bill line-item provenance

Location: `web/src/App.tsx:429–454` (issued documents) and the AccountPanel rating/invoice queries.

The portal displays the invoice total and ledger account debits/credits, plus adjustment total deltas. It does not fetch or render the immutable rating lines, quantities, unit rates, tariff/period provenance or calculation explanation for the selected invoice. Operators cannot perform the specified import/bill/**explain**/correct journey: ledger legs do not explain how metered usage became a charge. The accepted operator contract explicitly requires bill/line-item provenance and browser bill explanation. This is the residual itemised-portal gap already identified in the historical M2 review, now confirmed by source inspection rather than treated as completed.

Add an invoice-linked explanation view using the issued document's pinned calculation evidence (and authoritative calculation source), with a browser/API regression that distinguishes historical issued inputs from subsequent re-rating. Owner: TAR-009. No browser automation was run in this review; this finding is based on the concrete query and render omissions.

## Verification

- Existing billing tests: `.venv/bin/pytest -q tests/test_billing.py --tb=short` — **16 passed**. Covers concurrent admission/issuance, immutable records, unbalanced nonempty journals, sealed posting sets, stale inputs, outbox recovery and subprocess death before commit.
- New probes: `.venv/bin/pytest -q docs/project/evidence/m1_foundation_probes.py -c pyproject.toml --tb=short` — **2 failed**, demonstrating F1 and F2. Tests express the desired contract and must turn green after remediation; no xfail markers. F2 simulates calculator unavailability, not a real broker outage.
- PostgreSQL was initially inaccessible inside the restricted network sandbox (16 setup errors). Scoped escalated execution succeeded against localhost:55432 and the isolated pytest database. The setup failure is an environment limitation, not an application regression.
- `UV_CACHE_DIR=/tmp/taryx-review-uv make check` — **passed**: Ruff lint/format, mypy (87 source files), import contracts including rejection of the deliberate violation, **148 pytest tests**, **6 frontend tests**, frontend typecheck and production build.
- Preserved probes: `.venv/bin/pytest -q docs/project/evidence/m1_review_probes.py docs/project/evidence/m2_review_probes.py docs/project/evidence/m2_followup_probes.py -c pyproject.toml --tb=short` — **18 passed**.
- New probe Ruff checks and `git diff --check` — passed. Detailed outcomes above are the retained evidence; transient command logs are under `/tmp/taryx-m1-*.log`.

## Limitations and disposition

No fresh interactive browser journey, real broker interruption, worker kill after commit/before acknowledgement, hosted CI, deployment or throughput campaign was performed. Existing passing tests do not establish those scenarios. The operator source was reviewed alongside API permission/idempotency tests in the project suite.

Reopen TAR-007 and TAR-009 as Ready for remediation; canonical M2 remains In progress. Preserve the original metering M1 completion and historical evidence. Do not approve the user-named foundation M1 until findings are resolved and targeted plus required checks pass. No acceptance scope was changed.


## Remediation addendum — 2026-11-08 (Devin)

All three findings resolved:

- **F1**: `billing/migrations/0008` adds a deferred constraint trigger on `billing_journalentry` INSERT applying the same balanced-posting check at commit. An empty journal is now rejected; the 0004 seal guarantees it could never be completed later, so the insert-time commit check closes the gap. Valid journals (legs created later in the same transaction) still pass.
- **F2**: `drain_outbox` isolates failures per event — `attempts`/`last_error` recorded on the `OutboxEvent` row (migration 0008), later events still process, events past `max_attempts` (10) stay undelivered but unselected so a permanently failing batch cannot occupy the drain. All events are attempted before the first failure is re-raised.
- **F3**: `InvoiceType` exposes `calculationSource` and the pinned `ratingRun` (lines with tariff/segment/quantity/rate/amount/gst/basis plus engine and policy identity). The portal's issued documents expand per invoice into full line-item provenance.

Verification: both probes pass and are folded into `tests/test_billing.py`; `test_invoice_line_items_pin_the_issued_calculation` in `tests/test_graphql.py` verifies the pinned run survives re-rating; `make check` green (151 pytest, 6 vitest, typecheck, build, ruff/mypy/import contracts).
