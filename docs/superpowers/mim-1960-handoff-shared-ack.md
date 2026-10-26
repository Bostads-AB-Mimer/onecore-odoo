# MIM-1960 — handoff: change acknowledgement from per-audience to shared

Written 2026-08-27 so this can be picked up in a fresh session. Read this
first; it is the complete state.

## Where things stand

| | |
|---|---|
| Odoo branch | `feature/mim-1960-hantering-av-meddelanden-fran-kund-via-mina-sidor` |
| Odoo tip | `34570b7`, pushed, matches origin |
| Odoo PR | onecore-odoo#281 (draft) → `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements` |
| onecore branch | `feature/mim-1960-receipt-to-tenant-on-mina-sidor`, tip `4252b67`, pushed |
| onecore PR | onecore#717 (draft) → `epic/mim-1983` |
| Test suite | 492 tests, 0 failed (Odoo) · 49 tests, 0 failed (onecore work-order) |
| Module version | manifest at `19.0.1.0.6` |

Environment notes that will bite you:

- The git worktree at `.claude/worktrees/mim-1960` was **deleted** mid-session.
  All commits are safe, but untracked working docs inside it were lost (the
  original plan, spec, upgrade-verification report). The main checkout at
  `/Users/simonkropp/Documents/Prototyp/Projects/Mimer/onecore-odoo` is now
  sitting on the **feature branch**, not the epic branch.
- `run_tests.sh` fails with `OSError: Address already in use` because the dev
  Odoo holds port 8069 and the script does not forward flags. Invoke odoo-bin
  directly with `--http-port=8098`. Its exit code is worthless — grep the log
  for the `N failed, M error(s) of K tests` line.
- The suite installs modules into a fresh DB and never upgrades, so migrations
  do not execute during tests. Migration tests call the migration function
  directly.

## What the owner reported (PR #281, 2026-08-27T12:48Z)

Paraphrased: a contractor acknowledges → receipt posts, tenant sees it on Mina
sidor, all correct. Then logging in as an equipment manager or admin, the case
is **still flagged**, and that user can acknowledge **again** — which posts a
**second** receipt to Mina sidor and the chatter.

Their conclusion, which is the decision to implement:

> "I think the right way is to let the first person acknowledging the message
> to silence the nytt meddelande status for all audiences."

## Diagnosis — two separate things

**1. Still flagged for the other audience: working as designed, and that design is what's being changed.**
Acknowledgement is currently per-audience: Mimer and external contractors each
have their own timestamp, deliberately, so a contractor's acknowledgement cannot
suppress the tenant's message for Mimer. That was MIM-1844's explicit decision
and this branch preserved it. The owner has now seen it in practice and wants it
reversed. That is their call.

**2. The second receipt should already be impossible — cause not established.**
`34570b7` added a guard so only the *first* acknowledger posts a receipt: before
writing its own timestamp it reads the other audience's unread flag and posts
only if that flag is still `True`. Walking contractor-then-admin through that
logic yields no second receipt, and a test proves it (`test_second_ack_after_contractual…`
family in `test_customer_message_indicator.py`).

Two candidate explanations, unresolved:

- **Stale deployment.** `34570b7` was committed 2026-08-27T08:06Z, about 6.5
  hours before the report — so the environment *could* have had it, but may not.
  Check `ir_module_module.latest_version` and whether the deployed build
  contains `34570b7`.
- **Audience misdetection.** If the "admin" used for testing carries
  `group_external_contractor`, `is_external_contractor()` returns True for them,
  the guard reads the *internal* flag (still True), and a second receipt posts —
  reproducing the report exactly. Note `base.user_root` **is** in that group
  (`security/maintenance.xml:19-26`). Worth checking which user was used.

**This does not block the work.** Moving to a shared acknowledgement makes the
double-receipt path structurally impossible, so the fix supersedes the
diagnosis. Still worth confirming which cause it was, so we know whether a
latent audience-detection bug exists elsewhere.

## The concern to state once, then proceed

Reversing to a shared acknowledgement means Mimer handlers lose the "a tenant
wrote and nobody at Mimer has looked" signal on any case a contractor opened
first. If Mimer relies on that badge for oversight of contractor-handled cases,
that visibility goes away — the message is still in the chatter, but nothing
prompts anyone. The owner has seen the current behaviour in practice and judged
the duplicate-receipt and duplicate-status cost higher. Implement what they
asked for; do not re-litigate.

## What to build

Collapse the two audience columns into one shared acknowledgement. This makes
the feature *smaller* — several branches disappear.

### Model — `onecore_maintenance_extension/models/maintenance.py`

- Keep `customer_message_ack_at`. **Drop** `customer_message_external_ack_at`.
- Replace the two stored booleans `customer_message_unread_internal` /
  `customer_message_unread_external` with one stored boolean, e.g.
  `customer_message_unread`, computed as
  `last_customer_message_at and (not ack or last_customer_message_at > ack)`.
- `has_unread_customer_message` no longer needs `@api.depends_context("uid")`
  and no longer branches on audience — it just reads the single stored boolean.
  Consider whether it is still worth keeping as a separate non-stored field at
  all, or whether views should read the stored one directly. Keeping the name
  avoids touching the views and the JS.
- `action_acknowledge_customer_message`: drop the `is_external` branch for the
  timestamp. Keep the `if not self.has_unread_customer_message: return True`
  no-op guard — with a shared ack it now also stops the second acknowledger
  posting anything, which is exactly the reported bug.
- The receipt guard (`other_side_unread`) **disappears entirely**. With one
  shared ack, reaching the write means you are the first acknowledger, so the
  receipt posts unconditionally there. Multi-message still works: a new tenant
  message advances `last_customer_message_at` past the ack, the flag goes True
  again, and the next acknowledgement posts a fresh receipt.
- `_post_customer_message_receipt(is_external)` keeps its `is_external`
  parameter — the *body* still names Mimer vs the contractor's team, which is
  wanted. Only the *gating* becomes audience-blind.
- `_order`: `customer_message_unread desc, recently_added_tenant desc, request_date desc`.
- `FieldChangeTracker.SKIP_FIELDS`
  (`models/services/maintenance_workflow_service.py:152`) still needs
  `last_customer_message_at`. Check whether the renamed/removed booleans need
  entries — the earlier review established stored-compute writes bypass
  `write()` via `env.protecting`, so they do not.

### Migration — new `19.0.1.0.7`

`19.0.1.0.6` has been deployed to at least one test environment, so **do not
amend it**. Leave both `19.0.1.0.6` files exactly as they are; they were
verified against a restore of the production dump and must not be touched.

New `migrations/19.0.1.0.7/pre-migration.py`:

1. Merge the two columns into `customer_message_ack_at`, taking the **earliest
   non-null** of the pair — that is the first acknowledger, which is the new
   semantic. Handle each NULL case: only internal set → keep it; only external
   set → use it; both set → the earlier; neither → stays NULL.
2. Drop `customer_message_external_ack_at`.
3. Guard every step on column existence so it is idempotent and safe on a
   database that already ran it.

Then make sure the single stored boolean is recomputed — raw SQL bypasses the
ORM, so use `env.add_to_compute` as `19.0.1.0.6/post-migration.py` does (real
API; precedent at `odoo/addons/base/wizard/base_partner_merge.py:466`). Bump the
manifest to `19.0.1.0.7`.

Note this discards `customer_message_external_ack_at`'s distinct values. That is
inherent to the decision and acceptable; say so in the docstring.

### Tests

`onecore_maintenance_extension/tests/models/test_customer_message_indicator.py`
has substantial coverage that now asserts the *old* semantics. Rewrite rather
than delete: the per-side tests become shared-ack tests.

Must cover:

- The first acknowledger silences the status for **both** audiences — assert
  from a contractor and from an internal user, both orders.
- The second acknowledger's `action_acknowledge_customer_message` is a **no-op**:
  posts no receipt, and does not move the timestamp.
- Exactly **one** receipt exists on the record after both audiences have tried.
- The receipt body still names the correct party — Mimer when an internal user
  acknowledged first, the team name when a contractor did.
- A **new** tenant message re-raises the status for everyone and its next
  acknowledgement posts a fresh receipt. This is the case a careless
  implementation breaks; it was broken once already on this branch.
- Migration: earliest-non-null merge across all four NULL combinations, the
  column is gone afterwards, the stored boolean is recomputed, and a re-run
  changes nothing.

### Traps that have already cost time on this branch

- `create_maintenance_request()` returns a record carrying
  `creating_records=True`, and `write()` skips `FieldChangeTracker` under that
  context (`maintenance.py:1163`). Any test asserting a chatter note **is**
  posted must clear it first via `with_context(creating_records=False)`, or it
  passes vacuously. This has bitten four times.
- `fields.Datetime` truncates to whole seconds, so a message posted in the same
  wall-clock second as an acknowledgement does not compare as newer. Existing
  tests work around it by forcing `later.date = ack + timedelta(seconds=1)` and
  writing `last_customer_message_at` explicitly.
- The ORM defers stored-field writes and can serve reads from cache. In
  migration tests, `env.flush_all()` before invoking the migration and assert
  the **raw column** via `cr.execute` afterwards.
- Every new or changed test must be shown to fail. Mutate the implementation,
  watch the specific test fail, restore, confirm green. Four vacuous tests were
  caught this way on this branch, one of them the guard against sending real SMS
  to tenants.

## Also needs updating when the code is done

- **PR #281 body** — the section "Om kvittensen till hyresgästen" describes the
  first-acker receipt guard, and the decisions list says acknowledgement is
  per-audience. Both become wrong.
- **Test plan artifact** — https://claude.ai/code/artifact/2eceeb8c-9692-4161-be8e-5e731a4b9cff
  Test 05 ("Varje part kvitterar för sig") asserts the badge remains for the
  contractor after Mimer acknowledges. That expectation inverts. Test 06 also
  needs its "acknowledge as contractor first" step revisited. Re-publish to the
  same URL by republishing the same file path, or pass the URL explicitly.
- **onecore PR #717** needs no change — the allowlist entry is unaffected.

## Do not touch

- `migrations/19.0.1.0.6/pre-migration.py` and `post-migration.py` — verified
  against real production data (896 requests with tenant-message history, 367
  correctly left flagged, 338 notification-less requests correctly baselined as
  read). Reviewed twice. The new migration builds on top.
- `migrations/19.0.1.0.5/post-migration.py` — retained behind a `column_exists`
  guard at the owner's request. Deleting it aborts every upgrade crossing that
  version with `ProgrammingError`.
- The `receipt_to_tenant` message type must never start with `tenant_`:
  `onecore_mail_extension/models/mail_message.py:243` dispatches every
  `tenant_*` type as a real SMS or email to the tenant.
