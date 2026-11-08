# Independent M1 foundation re-review

Current reviewed SHA: `c270a3223c399902d4776a1e860a885d1c35a190`. Current verdict: **CHANGES_REQUESTED** (F1 resolved; F2/F3 remain open). See the round-two addendum below; earlier results are historical.

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

## Independent round-two re-review — 2026-11-08

Candidate: `c270a3223c399902d4776a1e860a885d1c35a190`.
Verdict: **CHANGES_REQUESTED**. F1 resolved; F2 and F3 partially remediated and remain open with the same finding IDs. The implementer's preceding resolution statement is historical, not independent approval. HEAD matched the candidate; only the untracked round-two event log existed before review and was preserved.

### F1 — Resolved

Migration 0008 schedules a deferred balance/presence check on journal INSERT. It evaluates the final posting set, rejecting an empty committed journal while allowing valid legs added within the creating transaction. The original independent empty-journal probe now passes.

### F2 — High, still open: exhausted transient failures become permanently pending

Location: `src/taryx/core/billing/services.py:435–448`; `src/taryx/composition/management/commands/drain_outbox.py`.

Per-event isolation fixes the original same-batch starvation. However, the new `attempts__lt=10` predicate permanently excludes any event after ten failures, including ordinary temporary dependency outages. There is no next-retry time, reset/requeue API or management-command option. After service recovery the standard drain silently returns no work for the exhausted operation; its status stays PENDING and its outbox stays undelivered. Retrying the public bill mutation returns that existing operation without enqueueing it. This also leaves it in flight for cohort guards. Direct database edits or manually calling internal processing functions are not an implemented operator recovery path.

The follow-up probe exhausts ten synthetic transient failures, restores a valid calculator and invokes the normal drain. The operation must recover but remains pending. Use fair retry scheduling/backoff that revisits recoverable work, or provide an explicit observable exhausted state and supported operator requeue path. Keep failure isolation and bounded batches; ensure old failures cannot occupy all recovery slots indefinitely. Owner: TAR-007.

### F3 — Medium, still open: legacy invoices show the wrong engine's lines

Location: `web/src/App.tsx:476–490`; `src/taryx/interfaces/graphql/schema.py:245`.

The expander correctly uses the pinned run for new-engine invoices, and the new GraphQL regression covers that case. For `calculationSource=legacy`, however, `Invoice.rating_run` still contains the **new-engine** reference calculation. The invoice totals came from the authoritative legacy calculator. The UI always renders `inv.ratingRun.lines`, so it presents different quantities/amounts and the new engine's identity under a legacy invoice. Displaying the source label does not make those lines explain the issued total.

The follow-up probe issues a balanced synthetic legacy result of $8.68 against a pinned new-engine run of $8.65, then executes the exact explanation field path used by the portal. The displayed lines sum to $8.65, not $8.68. This uses the supported injected calculator boundary, not a live legacy service. Expose and render immutable authoritative calculation evidence for the issued document; clearly separate any comparison calculation. Verify both new and legacy sources, including preservation after re-rating. Owner: TAR-009. This is the authoritative-source portion of original F3, not an added migration milestone requirement.

### Round-two checks and limits

`UV_CACHE_DIR=/tmp/taryx-review-uv make check` passed: Ruff lint/format, mypy (88 source files), import contracts and deliberate violation rejection, **151 backend tests**, **6 frontend tests**, frontend typecheck/build.

`.venv/bin/pytest -q docs/project/evidence/m1_foundation_probes.py docs/project/evidence/m1_followup_probes.py docs/project/evidence/m1_review_probes.py docs/project/evidence/m2_review_probes.py docs/project/evidence/m2_followup_probes.py -c pyproject.toml --tb=short` completed with **20 passed, 2 failed**. All prior probes pass; new F2 and F3 probes fail exactly as described above. Logs are transiently retained at `/tmp/taryx-m1-r2-check.log` and `/tmp/taryx-m1-r2-probes.log`.

Probe Ruff lint/format, changed-record links/UTF-8/status consistency and `git diff --check` passed. Both follow-up probes are retained in `m1_followup_probes.py` as desired-behaviour tests, without xfail. The original tests remain unchanged. No fresh browser automation, real broker outage, after-commit/before-ack kill, hosted CI or deployment was performed; the existing limitations still apply.


## Round-2 remediation addendum — 2026-11-08 (Devin)

- **F2** (retry exhaustion): the `max_attempts` cap is removed. Pending events are never excluded; `drain_outbox` selects by `attempts, created_at` so chronic failures sink below fresh work — bounded starvation without a terminal state — and a recovered dependency completes on the next ordinary drain. `attempts`/`last_error` remain the observable retry state.
- **F3** (authoritative explanation): `Invoice.legacy_calculation_id` (billing 0009) pins the shadow-alias `LegacyCalculation` whose response produced the invoice; `calculate_for_billing` records it on the op at calculation time. `invoice.ratingRun` now resolves per `calculationSource`: the real `RatingRun` for `new`, the pinned legacy response's own lines for `legacy` (tariff/segment/quantity/rate/amount/gst/basis from `response_json`). With no pinned response the resolver emits an explicitly labelled aggregate line reconciling to net+gst — never the new-engine run's lines. `RatingRunType`/`RatingLineType` are attribute-compatible `ObjectType`s so both evidence shapes serve the one contract.

Verification: all 4 preserved probes pass (foundation + follow-up); follow-ups folded into `tests/test_billing.py` and `tests/test_graphql.py`; `make check` green (153 pytest, 6 vitest, lint/format/mypy/contracts/build).
