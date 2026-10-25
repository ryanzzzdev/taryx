# Independent M1 confirmation and M2 review

Date: 2026-10-25
Reviewed commit: `2a46650`; working tree clean before review.
Verdict: Original M1 findings confirmed resolved. M2 reopened for seven findings below. No application code changed.

## Checks and scope

- `make check`: PASS, including 92 PostgreSQL tests, Ruff lint/format, mypy, import contracts and deliberate boundary violation, frontend typecheck/build.
- Saved M1 probes: `uv run pytest docs/project/evidence/m1_review_probes.py -c pyproject.toml -q` → **10 passed**. Reviewed corrected parsing, savepoint-contained hash deduplication, locked selection and quarantine resolution. M1 remains Complete for its original scope.
- New M2 probes: `uv run pytest docs/project/evidence/m2_review_probes.py -c pyproject.toml -q -p no:cacheprovider --tb=short` → **six regression targets fail** on this commit. They use pytest's PostgreSQL test database, including a separate connection committing a revision during issuance. Application demo data was not reset.
- Live browser at `http://localhost:5174/`: seeded operator login fails. API logs confirm an Origin-check rejection; the visible portal reports an HTML-as-JSON parse error. No financial browser mutation was performed, and a complete browser billing journey could not be exercised.
- Frontend recovery findings below also use direct source inspection. No fresh image rebuild, hosted CI, throughput campaign or after-commit/before-ack process kill was performed. Existing subprocess-before-commit tests passed; that is not evidence of the deferred kill-after-commit scenario.
- During probe development, the conflict case initially omitted export coverage and was corrected. A single conflicting value changed other intervals' source identities and correctly went stale. The retained all-interval conflict fixture isolates the actual bug: quarantine changes while all selected source records remain unchanged.

## R1 — P1: Make the documented portal origin and CSRF bootstrap work

Locations: `web/vite.config.ts:11`, `web/src/App.tsx:44`, `src/taryx/config/urls.py:23` and Django settings.

Opening the documented portal and signing in yields `Unexpected token '<'` because POST `/graphql` returns HTTP 403 HTML. Logs state `Origin checking failed - http://localhost:5174 does not match any trusted origins`. Vite rewrites Host to the API target with changeOrigin, while the browser retains the portal Origin and no trusted-origin setting accommodates it. The client also immediately POSTs `me` without first obtaining a CSRF cookie; `ensure_csrf_cookie` cannot bootstrap a request rejected by CSRF middleware.

Fix the explicit development origin/proxy contract without disabling CSRF, bootstrap the token with a safe request and handle non-JSON/non-success responses. Add a real fresh-browser sign-in and token-rotation test; Django Client tests without enforce_csrf_checks and curl calls without Origin did not cover this. Owner: TAR-009.

## R2 — P1: Protect issuance input validation through commit

Location: `src/taryx/core/billing/services.py:228–254`; digest inputs in `src/taryx/core/pricing/services.py`.

The operation row lock protects only that operation. A separate connection can commit revised meter data after the digest read and before issuance; the old calculation still posts as Complete. The digest also excludes open quarantine state: after rating, a full-day equal-precedence conflict leaves all selected records unchanged but creates open quarantines, and the admitted bill still issues.

The probes reproduce both paths. Issuance must revalidate coverage/conflict state and coordinate with input-changing operations through a shared revision/lock protocol covering validation and commit. Checking a hash earlier in the transaction is insufficient. Exercise the same boundary for adjustments and agreement changes, not just first invoices. Owners: TAR-007/TAR-008; TAR-006 input snapshot contract.

## R3 — P2: Post negative invoices with the correct ledger side

Location: `src/taryx/core/billing/services.py:158–164`.

The frozen profile allows net-credit bills. A valid high-export day rates to −$14.87, but `_issue` inserts a negative debit to receivables and violates `posting_single_leg`. The broad IntegrityError handler then mistakes the constraint failure for a competing issuance and raises Invoice.DoesNotExist. The operation remains pending rather than producing the supported bill or a useful terminal outcome.

Use sign-aware receivable postings as the correction path already does; only recover known uniqueness races, and surface other failures explicitly. Verify credit, zero-total and ordinary invoices. Owner: TAR-007.

## R4 — P1: Seal completed journal posting sets

Location: `src/taryx/core/billing/migrations/0002_financial_integrity.py` (posting trigger and immutability triggers).

Existing UPDATE/DELETE triggers do not prevent adding rows to an already-posted journal. The probe appends a balanced $1 debit/credit pair after issuance; the transaction commits. `_recognised_amounts` subsequently incorporates those new legs without an adjustment document, so the original recognised liability has changed despite the immutable-history claim. The deferred balance trigger cannot detect this because the modified journal still balances.

Introduce an enforceable draft-to-posted/sealed boundary or equivalent restricted posting mechanism: new journals may receive their initial postings transactionally, but existing posted journals may not gain additional legs. Exercise append attempts and empty-journal sealing as well as update/delete and balance checks. Owner: TAR-007; correction regression verification TAR-008.

## R5 — P2: Preserve immutable, reconstructible calculation evidence

Locations: `src/taryx/core/pricing/models.py:6–57`, `src/taryx/core/pricing/services.py:210–252`.

Invoice totals are protected, but their referenced RatingRun/RatingLine rows are ordinary mutable tables. The probe changes an issued bill's import quantity/amount to 999 successfully. These are the only stored itemised calculations; the input hash is not a retained snapshot that can reconstruct the exact reading selections, tariff bands and agreement values. Changing a referenced agreement also changes historical metadata behind the reference.

Persist the declared snapshot/versions or stable immutable references and protect calculation evidence once published/issued. Tests should reconstruct an old calculation after newer inputs exist and reject changes to its historical lines. This is a provenance contract gap even though the pure arithmetic reference tests pass. Owner: TAR-006, integrated verification TAR-007/TAR-009.

## R6 — P2: Resolve an existing operation before selecting a fresh rating run

Location: `src/taryx/interfaces/graphql/schema.py:506–516`.

BillAccount selects the latest RatingRun on every call, while admission hashes the rating-run ID. Repeating the identical GraphQL request and operation ID after another rating produces `operation_conflict`, even if inputs/amounts are unchanged. This breaks unknown-response recovery: the caller did not change its request, the server changed the hidden payload.

For an existing key, validate the original public request and return its original operation. For new requests, make rating selection explicit or pin it once during admission. Include retry-after-rerating and concurrent identical-key admission tests. Owners: TAR-009/TAR-007.

## R7 — P2: Persist unique browser operation identities and resume them

Location: `web/src/App.tsx:190–191,255–275`.

The portal creates IDs from a useRef counter starting at zero (`web-ACC-001-1`), so refreshes and independent browser sessions reuse IDs. It persists neither the ID nor the pinned request and always advances the counter on another click. A lost response cannot be recovered with the same identity, and after refresh/rerating a legitimate new bill can collide with an earlier operation. There is no operation lookup/resume control or durable pending-request state.

Generate collision-resistant IDs, persist each pending intent before submission, reuse that ID after uncertain results and restore polling after reload. Reset/account-scope state and reject stale responses when switching accounts. Source-inspection finding; live end-to-end verification is blocked by R1. Add browser reload/lost-response/two-session tests. Owner: TAR-009.

## Milestone decision

M1 remains Complete. Reopen TAR-006–009 and M2; TAR-006 is Ready for snapshot remediation, dependent tasks return to Backlog pending that contract. Preserve earlier passing evidence as history. Do not start TAR-010 as the next milestone until the M2 correctness/portal gates pass.

The previous exit review's listed limitations do not waive accepted requirements on immutable history, stale-input issuance or browser recovery. Further readiness gaps (full itemised portal explanation, real broker fault testing, after-commit/ack failure and bounded query behaviour) should be mapped explicitly at re-review; this pass did not establish their completion.
