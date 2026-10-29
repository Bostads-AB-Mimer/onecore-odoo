# Tenant Close Request (MIM-2036) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn "Jag vill avsluta ärendet" on Mina sidor from a direct close into a request that the Odoo user accepts or declines, with its own purple badge and a pending state stored in Odoo.

**Architecture:** Odoo owns the state (`close_requested_at` / `close_request_resolved_at` / stored `close_request_pending`) and exposes `request_close_from_tenant` over XML-RPC. work-order and core gain a separate `close-request` route (the staff `/close` route used by property-tree is untouched). The .NET API keeps its Mina sidor URL, adds an ownership check and real error propagation, and calls core's new route. Mina sidor reads `closeRequestPending` and shows the request and any decline in the thread.

**Tech Stack:** Odoo 19 (Python, OWL, TransactionCase); onecore pnpm/Turborepo, TypeScript, Koa, Zod, Jest, msw, odoo-await; .NET 6, MediatR, xunit + Moq; Vue 3, Pinia, axios.

**Spec:** repo `onecore-odoo`, branch `feat/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism`, `docs/superpowers/specs/2026-09-25-mim-2036-tenant-close-request-design.md` (including its *Amendments from planning* section).

## Global Constraints

- Branches: `feat/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` (onecore-odoo) and `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` (onecore, API, Webbappar), each targeting its repo's MIM-1983 epic branch.
- Message types are exactly `close_request_from_tenant` and `close_request_declined`. No `tenant_` prefix (it triggers outbound SMS/e-mail).
- The Odoo conflict prefix is exactly `close_request_conflict:`, followed by `already_pending` | `closed` | `hidden`.
- The staff close path (`/workOrders/:id/close`, `/work-orders/:id/close`, both `closeWorkOrder` adapters) must not change.
- The Mina sidor endpoint URL `~/api/workorders/close/{workOrderId}` must not change.
- Swedish copy, verbatim:
  - badge "Hyresgäst vill avsluta"
  - buttons *Avsluta ärendet* / *Avslå*
  - "Begäran om att avsluta ärendet"
  - "Begäran om avslut är redan hanterad."
  - "Begäran om avslut skickad – väntar på svar"
  - "Det finns redan en begäran som väntar på svar"
  - thread labels "Begäran om avslut" / "Avslutsbegäran avböjd"
- Code, comments, identifiers, commit messages and PR text are English. Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never write to Xpand and never run tests against it. Destructive testing is local only.
- `pnpm run typecheck` and `pnpm run lint` in onecore must end at zero errors. `dotnet build` must be clean. `pnpm run lint` must pass in mina-sidor.
- Committed docs contain no local absolute paths or worktree paths.
- Release order: onecore-odoo, then onecore, then API and Webbappar **back to back**.

## Review Focus

- **A tenant double-clicks, or has two tabs open.** Exactly one request is stored. The second call ends as 409 and the button shows pending. Covered by the O3 row-lock test, C3 (409 end to end), and M2 + M3 (manual).
- **A reason contains HTML or `<script>`.** Mina sidor renders the body with `v-html`, so the reason must arrive escaped, never executed. Covered by the O3 escaping test and M3 (manual).
- **Core or Odoo is down when the tenant clicks.** The tenant sees an error, not "sent", the button stays enabled, and the typed reason is kept. Covered by C3 (fault → 500), A2 + A5 (UpstreamFailed → 502) and M2.
- **A contractor handles a close request.** They can decline, with their resource-group sender shown to the tenant, and are never offered accept. Covered by O4, O5 and O7.
- **A case is closed by a normal stage drag while a request is pending, then reopened.** The request resolves on close, and a new request is possible after reopening. Covered by O4 and O3.

---

### Task 0: Move the stacked branches onto the epics once MIM-2040 has landed

While MIM-2040 is still being merged, the MIM-2036 branches in onecore, onecore-odoo and Webbappar are **stacked** on the MIM-2040 branches, and work on them goes ahead. The API branch sits on its epic, because MIM-2040 does not touch the API. Keep PRs in the three stacked repos as drafts until this task is done. None of the stacked branches has an upstream set, so always push with an explicit `origin <branch>`.

| Repo | Stacked on | Moves onto |
|---|---|---|
| onecore | `feature/mim-2040-tenant-facing-sender-on-work-order-messages` | `epic/mim-1983` |
| onecore-odoo | `feature/mim-2040-se-till-att-avsandare-pa-meddelande-till-hyresgast-pa-mina` | `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements` |
| Webbappar | `feature/mim-2040-show-full-sender-on-work-order-messages` | `epic/mim-1983-odoo-prioritized-ux-and-communication-improvements` |

**Files:** none (git only)

- [ ] **Step 1: Confirm MIM-2040 is merged into each epic**

```sh
git -C onecore fetch -q && git -C onecore log --oneline origin/epic/mim-1983 | grep -m1 MIM-2040
git -C onecore-odoo fetch -q && git -C onecore-odoo log --oneline origin/epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements | grep -m1 MIM-2040
git -C mimer-nu/Webbappar fetch -q && git -C mimer-nu/Webbappar log --oneline origin/epic/mim-1983-odoo-prioritized-ux-and-communication-improvements | grep -m1 MIM-2040
```

Expected: each command prints a MIM-2040 commit. If a command prints nothing, leave that repo stacked.

- [ ] **Step 2: Move each branch off MIM-2040 and onto its epic**

`--onto` replays only the MIM-2036 commits. This works even if MIM-2040 was squash-merged or rebased on its way into the epic.

```sh
F=mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism
git -C onecore rebase --onto origin/epic/mim-1983 origin/feature/mim-2040-tenant-facing-sender-on-work-order-messages feature/$F
git -C onecore-odoo rebase --onto origin/epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements origin/feature/mim-2040-se-till-att-avsandare-pa-meddelande-till-hyresgast-pa-mina feat/$F
git -C mimer-nu/Webbappar rebase --onto origin/epic/mim-1983-odoo-prioritized-ux-and-communication-improvements origin/feature/mim-2040-show-full-sender-on-work-order-messages feature/$F
```

The Webbappar MIM-2040 branch may have been rebased itself, and its old tip then no longer matches `origin/feature/mim-2040-…`. In that case, use the tip the MIM-2036 branch was actually stacked on (`git merge-base`) as the second argument.

- [ ] **Step 3: Re-run each repo's suite, then take the PRs out of draft.** Run `./run_tests.sh` in onecore-odoo, `pnpm run build:libs && pnpm run typecheck && pnpm run lint && pnpm test` in onecore, and `pnpm run lint && pnpm run build` in mina-sidor. Force-push with `--force-with-lease origin <branch>`, and ask first.

---

## onecore-odoo (Tasks O1–O7)

**Repo:** `onecore-odoo`, branch `feat/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism`, rebased onto `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements` **after MIM-2040 has been merged there**. Every task below assumes MIM-2040's `onecore_mail_extension/models/mail_message.py` (`TENANT_FACING_MESSAGE_TYPES`, `EXPECTED_TENANT_FACING`, `onecore_tenant_author_name`), its `tests/test_tenant_author_name.py`, and its manifest version `19.0.1.0.1`. Before Task O1, run `git log --oneline -1 -- onecore_mail_extension/tests/test_tenant_author_name.py`. If that prints nothing, MIM-2040 has not landed yet, so stop and rebase first.

### Odoo constraints for this section

- **Line numbers** below are from the current epic tip. MIM-2040 adds 6 lines to the `_post_customer_message_receipt` docstring in `models/maintenance.py` (~line 729). Every range in `maintenance.py` after that point therefore moves down by 6 once rebased. Match on the quoted surrounding lines, not on the number.
- **Never test as the raw `self.env`.** `security/maintenance.xml` puts `base.user_root` (the TransactionCase uid) in `group_external_contractor`, so `self.env` is refused a move to *Avslutad* the same way a contractor is. Stage writes and staff actions go through `with_user(internal_user)`.
- **No migration.** The three new columns start NULL/False on existing rows. That is the correct state, because no request exists yet. Odoo computes the new stored boolean for existing rows by itself when the upgrade runs. The manifest versions are still bumped (maintenance `19.0.1.0.11` → `19.0.1.0.12`, mail `19.0.1.0.1` → `19.0.1.0.2`), because every change to the schema or a selection in this repo gets a bump. Note that the `odoo-module-upgrade` Job upgrades every `onecore_*` module regardless of version.
- **No CHANGELOG** exists in this repo, so no changelog or docs entry is added.
- **`tenant_*` prefix is forbidden** for the new types. `mail.message.create()` dispatches every `tenant_*` type as an outbound SMS or e-mail.

### Test commands

`run_tests.sh` hardcodes `--test-tags=onecore` and sources `.env` from its own directory. `.env` is gitignored, so a fresh worktree does not have one. Before the first run, copy `.env` from the main `onecore-odoo` checkout and set `ODOO_ONECORE_PATH` to this checkout's path. Otherwise the tests run against the main checkout.

To run selected classes, rewrite the tag on the fly (from the worktree root; piping into `bash` makes `SCRIPT_DIR` resolve to the cwd):

```sh
sed 's#--test-tags=onecore#--test-tags=<SPEC>#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

`<SPEC>` is a comma-separated list of `/<module>:<ClassName>`. The last line printed is Odoo's summary, `odoo.tests.result: N failed, M error(s) of K tests ...`. PASS means `0 failed, 0 error(s)`. The whole suite is plain `./run_tests.sh`.

---

### Task O1: Message types, constants and log/tenant-facing classification

**Files:**
- Modify: `onecore_mail_extension/models/mail_message.py`:
  - `TENANT_FACING_MESSAGE_TYPES` (post-MIM-2040 lines 29–37)
  - `message_type` `selection_add`/`ondelete` (~lines 219–258)
  - `EXPECTED_CATEGORIES` (~678–713)
  - `EXPECTED_TENANT_FACING` (~726–756)
- Modify: `onecore_mail_extension/__manifest__.py` (line 6, `version`)
- Modify: `onecore_maintenance_extension/models/constants.py` (lines 85–92, append)
- Test: `onecore_mail_extension/tests/test_log_category.py` (after `test_receipt_to_tenant_is_communication`, lines 103–110)
- Test: `onecore_mail_extension/tests/test_tenant_author_name.py` (from MIM-2040, append to `TestTenantAuthorName`)
- Test (create): `onecore_maintenance_extension/tests/models/test_close_request.py`
- Modify: `onecore_maintenance_extension/tests/__init__.py` (append), `onecore_maintenance_extension/tests/models/__init__.py` (append)

**Interfaces:**
- Consumes: MIM-2040's `TENANT_FACING_MESSAGE_TYPES`, `EXPECTED_TENANT_FACING` and `TestTenantAuthorName._post()`
- Produces:
  - `mail.message.message_type` values `close_request_from_tenant` and `close_request_declined`
  - Constants `CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE`, `CLOSE_REQUEST_DECLINED_MESSAGE_TYPE` and `CLOSE_REQUEST_CONFLICT_PREFIX = "close_request_conflict:"` in `constants.py`
  - `close_request_declined` is tenant-facing, so it carries `onecore_tenant_author_name`. `close_request_from_tenant` is not.

- [ ] **Step 1: Write the failing tests**

In `onecore_mail_extension/tests/test_log_category.py`, insert after `test_receipt_to_tenant_is_communication` (after line 110):

```python
    def test_close_request_types_are_communication(self):
        """MIM-2036: both halves of the close-request exchange carry the
        internal mail.mt_note subtype, like the receipt, and are read by the
        tenant on Mina sidor — so they belong in Kommunikation."""
        for message_type in ("close_request_from_tenant", "close_request_declined"):
            with self.subTest(message_type=message_type):
                message = self._message(message_type, self.note_subtype)
                self.assertEqual(
                    message.onecore_log_category, LOG_CATEGORY_COMMUNICATION
                )
```

In `onecore_mail_extension/tests/test_tenant_author_name.py`, append to `TestTenantAuthorName`:

```python
    def test_close_request_declined_names_the_contractors_resource_group(self):
        # MIM-2036: a contractor may decline a tenant's close request, and the
        # tenant must see which supplier answered rather than a bare "Mimer".
        message = self._post(self.external_user, message_type="close_request_declined")
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_close_request_from_tenant_carries_no_sender_label(self):
        # The tenant's own words, posted on their behalf by the integration:
        # Mina sidor labels it "Du", exactly like from_tenant.
        message = self._post(
            self.internal_user, message_type="close_request_from_tenant"
        )
        self.assertFalse(message.onecore_tenant_author_name)
```

Create `onecore_maintenance_extension/tests/models/test_close_request.py`:

```python
"""Tests for the tenant's close request (MIM-2036).

A tenant can no longer close an Odoo case from Mina sidor. They ask, via
request_close_from_tenant, and an Odoo user decides: "Avsluta ärendet"
(action_accept_close_request) or "Avslå" with a reason (the decline wizard).
Moving the case to Avslutad any other way also resolves the request.
"""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...models.constants import (
    CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
)


@tagged("onecore")
class TestCloseRequestMessageTypes(TransactionCase):
    def test_types_are_registered_on_mail_message(self):
        # Assert on the constants, not literals, so renaming one side without
        # the other (constants.py vs onecore_mail_extension) fails here.
        selection = dict(self.env["mail.message"]._fields["message_type"].selection)
        self.assertIn(CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE, selection)
        self.assertIn(CLOSE_REQUEST_DECLINED_MESSAGE_TYPE, selection)

    def test_types_are_not_outbound_tenant_dispatch_types(self):
        # Every tenant_* type sends a real SMS/e-post in mail.message.create.
        for message_type in (
            CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
            CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
        ):
            with self.subTest(message_type=message_type):
                self.assertFalse(message_type.startswith("tenant_"))
```

Append to `onecore_maintenance_extension/tests/__init__.py` (after `from .models import test_remove`):

```python
from .models import test_close_request
```

Append to `onecore_maintenance_extension/tests/models/__init__.py` (after `from . import test_remove`):

```python
from . import test_close_request
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_mail_extension:TestOneCoreLogCategory,/onecore_mail_extension:TestTenantAuthorName,/onecore_maintenance_extension:TestCloseRequestMessageTypes#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected:
- `ImportError: cannot import name 'CLOSE_REQUEST_DECLINED_MESSAGE_TYPE'` while the `onecore_maintenance_extension` tests are imported
- `ERROR: TestOneCoreLogCategory.test_close_request_types_are_communication` with `ValueError: Wrong value for mail.message.message_type: 'close_request_from_tenant'`
- The same `ValueError` for both new `TestTenantAuthorName` tests

- [ ] **Step 3: Implement**

`onecore_mail_extension/models/mail_message.py`: in `TENANT_FACING_MESSAGE_TYPES`, add the decline after `"tenant_my_pages",`:

```python
TENANT_FACING_MESSAGE_TYPES = frozenset(
    {
        "receipt_to_tenant",
        "tenant_sms",
        "tenant_mail",
        "tenant_mail_and_sms",
        "tenant_my_pages",
        # MIM-2036 — staff's answer to a tenant's close request. A contractor
        # may give it, and the tenant must see which supplier did.
        "close_request_declined",
    }
)
```

In the `message_type` field, extend `selection_add` after the `tenant_my_pages` tuple, and `ondelete` after its `tenant_my_pages` key:

```python
            ("tenant_my_pages", "Published to tenant on Mina sidor"),
            # MIM-2036 — the tenant asks for the case to be closed, and staff's
            # "no". Deliberately NOT prefixed tenant_ (same reason as
            # receipt_to_tenant): create() would dispatch them as SMS/e-post.
            ("close_request_from_tenant", "Begäran om avslut från hyresgäst"),
            ("close_request_declined", "Begäran om avslut avslagen"),
        ],
        ondelete={
            ...
            "tenant_my_pages": "set default",
            "close_request_from_tenant": "set default",
            "close_request_declined": "set default",
        },
```

(The `...` stands for the existing keys, which stay unchanged. Only the last two lines are new.)

In `EXPECTED_CATEGORIES`, after `"tenant_my_pages": LOG_CATEGORY_COMMUNICATION,`:

```python
    "tenant_my_pages": LOG_CATEGORY_COMMUNICATION,
    # MIM-2036 — both are read by the tenant on Mina sidor, so they belong in
    # the filter handläggare read as the tenant conversation.
    "close_request_from_tenant": LOG_CATEGORY_COMMUNICATION,
    "close_request_declined": LOG_CATEGORY_COMMUNICATION,
```

In `EXPECTED_TENANT_FACING`, after `"tenant_my_pages": True,`:

```python
    "tenant_my_pages": True,
    # MIM-2036. The request is the tenant's own words, posted on their behalf
    # by the integration — Mina sidor labels it "Du", like from_tenant. The
    # decline is ours and may come from a contractor, so it is labelled.
    "close_request_from_tenant": False,
    "close_request_declined": True,
```

`onecore_mail_extension/__manifest__.py` line 6:

```python
    "version": "19.0.1.0.2",
```

`onecore_maintenance_extension/models/constants.py`: append after line 92 (`RECEIPT_TO_TENANT_MESSAGE_TYPE = "receipt_to_tenant"`):

```python

# MIM-2036 — the tenant asks for the case to be closed; an Odoo user declines.
# Same rule as above: the selection values live on mail.message in
# onecore_mail_extension, which cannot import this module. Keep in sync.
CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE = "close_request_from_tenant"
CLOSE_REQUEST_DECLINED_MESSAGE_TYPE = "close_request_declined"
# Every refusal from request_close_from_tenant starts with this, followed by
# already_pending, closed or hidden. onecore's work-order service matches on it
# to answer 409, so it is part of the cross-repo contract — never reword it.
CLOSE_REQUEST_CONFLICT_PREFIX = "close_request_conflict:"
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s)`. This includes MIM-2040's `test_every_message_type_is_classified_as_tenant_facing_or_not` and `test_expected_tenant_facing_matches_the_capture_list`, which only pass because both maps were updated.

- [ ] **Step 5: Commit**

```sh
git add onecore_mail_extension/models/mail_message.py onecore_mail_extension/__manifest__.py \
  onecore_mail_extension/tests/test_log_category.py onecore_mail_extension/tests/test_tenant_author_name.py \
  onecore_maintenance_extension/models/constants.py \
  onecore_maintenance_extension/tests/models/test_close_request.py \
  onecore_maintenance_extension/tests/__init__.py onecore_maintenance_extension/tests/models/__init__.py
git commit -m "Add close-request message types for tenant close requests (MIM-2036)

close_request_from_tenant carries the tenant's request, close_request_declined
staff's answer. Both are Kommunikation in the log filter; only the decline is
tenant-facing for the MIM-2040 sender label, since a contractor may give it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O2: Close-request fields, pending compute and kanban order

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py`:
  - `_order` (lines 62–65)
  - Fields, after `has_unread_customer_message` (lines 213–217)
  - Compute, after `_compute_has_unread_customer_message` (lines 671–677)
- Modify: `onecore_maintenance_extension/models/services/maintenance_workflow_service.py` (`FieldChangeTracker.SKIP_FIELDS`, lines 206–236)
- Modify: `onecore_maintenance_extension/__manifest__.py` (line 6)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

**Interfaces:**
- Consumes: nothing new
- Produces:
  - `maintenance.request` fields `close_requested_at` (Datetime), `close_request_resolved_at` (Datetime) and `close_request_pending` (Boolean, stored compute)
  - `_order = "close_request_pending desc, customer_message_unread desc, recently_added_tenant desc, request_date desc"`
  - Test fixture `CloseRequestCase`

- [ ] **Step 1: Write the failing test**

In `test_close_request.py`, replace the import block with:

```python
from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
)
from .test_customer_message_indicator import _get_or_create_mimer_user
from ...models.constants import (
    CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
)
```

Then append to the file:

```python
class CloseRequestCase(TransactionCase):
    """Shared fixture: the integration account the work-order service calls
    as, a Mimer handler, and a contractor on the request's team.

    Staff actions always run as a dedicated user: security/maintenance.xml
    puts base.user_root — the raw test env — in group_external_contractor, so
    it would be refused a move to Avslutad like any contractor. The contractor
    record rule only grants access to requests on the contractor's own team.
    """

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )
        self.stage_avslutad = self._stage("Avslutad")
        self.stage_vantar = self._stage("Väntar på handläggning")

    def _stage(self, name):
        return self.env["maintenance.stage"].search([("name", "=", name)], limit=1)

    def _as(self, user):
        return self.request.with_user(user)

    def _fresh(self):
        # Writes made through another user's env (sudo, with_user) and
        # savepoint rollbacks must not be answered from a stale cache.
        self.request.invalidate_recordset()
        return self.request


@tagged("onecore")
class TestCloseRequestPending(CloseRequestCase):
    def _stamp(self, requested=False, resolved=False):
        self.request.sudo().write(
            {"close_requested_at": requested, "close_request_resolved_at": resolved}
        )

    def test_not_pending_without_a_request(self):
        self.assertFalse(self.request.close_request_pending)

    def test_pending_once_requested(self):
        self._stamp(requested=fields.Datetime.now())
        self.assertTrue(self._fresh().close_request_pending)

    def test_resolution_after_the_request_clears_it(self):
        now = fields.Datetime.now()
        self._stamp(requested=now - timedelta(minutes=5), resolved=now)
        self.assertFalse(self._fresh().close_request_pending)

    def test_resolution_in_the_same_second_clears_it(self):
        # Datetime has second resolution; a decline within the second of the
        # request must read as resolved, not as still pending.
        now = fields.Datetime.now()
        self._stamp(requested=now, resolved=now)
        self.assertFalse(self._fresh().close_request_pending)

    def test_request_after_a_resolution_is_pending_again(self):
        now = fields.Datetime.now()
        self._stamp(requested=now, resolved=now - timedelta(minutes=5))
        self.assertTrue(self._fresh().close_request_pending)

    def test_pending_close_request_sorts_before_an_unread_customer_message(self):
        # Without the new first key, customer_message_unread desc would put
        # `other` first — so this pins both the promotion and its precedence.
        other = create_maintenance_request(self.env, maintenance_team_id=self.team.id)
        other.sudo().write({"last_customer_message_at": fields.Datetime.now()})
        self._stamp(requested=fields.Datetime.now())
        found = self.env["maintenance.request"].search(
            [("id", "in", [self.request.id, other.id])]
        )
        self.assertEqual(found.ids, [self.request.id, other.id])

    def test_stamps_post_no_change_note(self):
        # The request and the decline are chatter messages of their own, and an
        # accept is the stage change — a field-change note on top is noise.
        before = len(self.request.message_ids)
        self._as(self.internal_user).write(
            {"close_requested_at": fields.Datetime.now()}
        )
        self.assertEqual(len(self._fresh().message_ids), before)
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestCloseRequestPending#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected: every test errors. The typical errors are `ValueError: Invalid field 'close_requested_at' in 'maintenance.request'` and `AttributeError: 'maintenance.request' object has no attribute 'close_request_pending'`. Summary: `0 failed, 7 error(s)`.

- [ ] **Step 3: Implement**

`models/maintenance.py`, lines 62–65. Replace the `_order` comment and line with:

```python
    _inherit = "maintenance.request"
    # A tenant's close request first — the only signal that asks for a
    # decision rather than an acknowledgement (MIM-2036) — then customer
    # messages, "ska sorteras högst upp i kanban vyn". _order takes stored
    # columns only, hence the stored booleans rather than their non-stored
    # has_unread_* mirrors.
    _order = "close_request_pending desc, customer_message_unread desc, recently_added_tenant desc, request_date desc"
    _unaccent = True
```

Fields: insert between `has_unread_customer_message` (ends line 217) and the `requires_pest_control` comment (line 218):

```python
    has_unread_customer_message = fields.Boolean(
        string="Okvitterat meddelande från kund",
        compute="_compute_has_unread_customer_message",
        store=False,
    )
    # MIM-2036 — "Hyresgäst vill avsluta". Two timestamps rather than a flag,
    # the same shape as last_customer_message_at / customer_message_ack_at: a
    # new request after a decline re-raises the signal simply by being newer
    # than the last resolution, with nothing to reset.
    close_requested_at = fields.Datetime(
        string="Avslut begärt av hyresgäst",
        readonly=True,
        copy=False,
        help="Sätts när hyresgästen ber om att få ärendet avslutat via Mina sidor.",
    )
    close_request_resolved_at = fields.Datetime(
        string="Begäran om avslut hanterad",
        readonly=True,
        copy=False,
        help="Sätts när begäran avslås, när ärendet avslutas på begäran eller när "
        "ärendet flyttas till Avslutad på annat sätt.",
    )
    # Stored, so _order can promote it and the kanban/mobile cards can read it
    # without a compute per card.
    close_request_pending = fields.Boolean(
        string="Hyresgäst vill avsluta",
        compute="_compute_close_request_pending",
        store=True,
    )
    # Stored snapshot written only by OneCoreFlagSyncService (create path +
```

Compute: insert after `_compute_has_unread_customer_message` (after line 677, before `def action_acknowledge_dialog`):

```python
    @api.depends("close_requested_at", "close_request_resolved_at")
    def _compute_close_request_pending(self):
        # One shared fact, like customer_message_unread — no depends_context.
        # request_close_from_tenant keeps a new request strictly after the last
        # resolution, so equal timestamps here always mean "resolved".
        for record in self:
            requested = record.close_requested_at
            resolved = record.close_request_resolved_at
            record.close_request_pending = bool(requested) and (
                not resolved or requested > resolved
            )
```

`models/services/maintenance_workflow_service.py`, in `SKIP_FIELDS` after `"last_customer_message_at",` (line 219):

```python
        "last_customer_message_at",
        # MIM-2036 close-request stamps. The request and the decline are
        # already in the chatter as messages of their own, and an accept as
        # the stage change.
        "close_requested_at",
        "close_request_resolved_at",
        "close_request_pending",
        "recently_added_tenant",  # technical flag, English label — never log
```

`onecore_maintenance_extension/__manifest__.py` line 6:

```python
    "version": "19.0.1.0.12",
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 7 tests`.

- [ ] **Step 5: Commit**

```sh
git add onecore_maintenance_extension/models/maintenance.py \
  onecore_maintenance_extension/models/services/maintenance_workflow_service.py \
  onecore_maintenance_extension/__manifest__.py \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Track pending tenant close requests on maintenance requests (MIM-2036)

close_requested_at and close_request_resolved_at drive a stored
close_request_pending, which becomes the first kanban sort key. The stamps
are excluded from field-change notes.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O3: `request_close_from_tenant` with row lock, escaping and refusals

**Files:**
- Modify: `onecore_maintenance_extension/models/utils/helpers.py` (imports lines 1–4, append a function)
- Modify: `onecore_maintenance_extension/models/maintenance.py`:
  - Imports (lines 1–31)
  - New section before `def _send_creation_sms` (line 786)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

**Interfaces:**
- Consumes:
  - `CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE` and `CLOSE_REQUEST_CONFLICT_PREFIX` (O1)
  - `close_requested_at`, `close_request_resolved_at` and `close_request_pending` (O2)
- Produces:
  - `maintenance.request.request_close_from_tenant(self, reason=None) -> True` (XML-RPC)
  - `maintenance.request._lock_for_close_request()`
  - `helpers.close_request_reason_html(reason) -> Markup | None`
  - Refusals raise `UserError("close_request_conflict:<already_pending|closed|hidden>")`

- [ ] **Step 1: Write the failing test**

Extend the import block of `test_close_request.py` to:

```python
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import SQL

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
)
from .test_customer_message_indicator import _get_or_create_mimer_user
from ...models.constants import (
    CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
)
```

Add this module-level helper below the imports:

```python
def _sql_code(call):
    """The query text of one recorded cr.execute call."""
    query = call.args[0] if call.args else call.kwargs.get("query")
    return query.code if isinstance(query, SQL) else str(query)
```

Add a method to `CloseRequestCase` (after `_fresh`):

```python
    def _messages(self, message_type):
        return self.env["mail.message"].search(
            [
                ("model", "=", "maintenance.request"),
                ("res_id", "=", self.request.id),
                ("message_type", "=", message_type),
            ]
        )
```

Append the class:

```python
@tagged("onecore")
class TestRequestCloseFromTenant(CloseRequestCase):
    def _request_close(self, reason=None):
        # Called exactly as onecore's work-order service does: XML-RPC as the
        # integration account.
        return self._as(self.mimer_user).request_close_from_tenant(reason=reason)

    def _requests(self):
        return self._messages(CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE)

    def test_request_posts_the_message_and_sets_pending(self):
        self.assertIs(self._request_close(), True)
        message = self._requests()
        self.assertEqual(len(message), 1)
        self.assertIn("Begäran om att avsluta ärendet", message.body)
        self.assertNotIn("Orsak", message.body)
        self.assertEqual(message.author_id, self.mimer_user.partner_id)
        # Tenant-authored: work-order takes the sender from author_id, so no
        # tenant-facing sender may be stored (MIM-2040).
        self.assertFalse(message.onecore_tenant_author_name)
        request = self._fresh()
        self.assertTrue(request.close_requested_at)
        self.assertTrue(request.close_request_pending)

    def test_reason_follows_orsak(self):
        self._request_close(reason="  Allt fungerar igen  ")
        self.assertIn("Orsak: Allt fungerar igen", self._requests().body)

    def test_reason_containing_a_script_tag_is_escaped(self):
        self._request_close(reason='<script>alert("x")</script>')
        body = self._requests().body
        # Escaped, not sanitised away: the HTML sanitiser would drop a live
        # <script> element entirely, so the escaped text surviving is what
        # proves the reason never reached the body as markup.
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script", body)

    def test_newlines_become_line_breaks(self):
        self._request_close(reason="Rad ett\nRad två")
        self.assertIn("Rad ett<br>Rad två", self._requests().body)

    def test_whitespace_only_reason_is_treated_as_none(self):
        self._request_close(reason="   \n\t  ")
        self.assertNotIn("Orsak", self._requests().body)
        self.assertTrue(self._fresh().close_request_pending)

    def test_second_request_is_refused_as_already_pending(self):
        self._request_close()
        with self.assertRaisesRegex(
            UserError, r"^close_request_conflict:already_pending$"
        ):
            self._request_close(reason="Igen")
        self.assertEqual(len(self._requests()), 1)

    def test_refused_when_the_case_is_closed(self):
        self._as(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        with self.assertRaisesRegex(UserError, r"^close_request_conflict:closed$"):
            self._request_close()
        self.assertFalse(self._requests())
        self.assertFalse(self._fresh().close_request_pending)

    def test_refused_when_hidden_from_my_pages(self):
        self.request.write({"hidden_from_my_pages": True})
        with self.assertRaisesRegex(UserError, r"^close_request_conflict:hidden$"):
            self._request_close()
        self.assertFalse(self._requests())

    def test_row_is_locked_before_the_checks(self):
        # Two concurrent calls cannot be staged in a TransactionCase — every
        # env shares one cursor — so this pins the mechanism instead: the lock
        # is taken even on a call that is then refused, i.e. before the check.
        self._request_close()
        cr = self.env.cr
        with patch.object(cr, "execute", wraps=cr.execute) as spy:
            with self.assertRaises(UserError):
                self._request_close()
        locks = [
            c
            for c in spy.call_args_list
            if "FOR UPDATE" in _sql_code(c) and "maintenance_request" in _sql_code(c)
        ]
        self.assertTrue(locks, "request_close_from_tenant must row-lock first")
        self.assertNotIn("SKIP LOCKED", _sql_code(locks[0]))

    def test_request_right_after_a_resolution_is_pending(self):
        # Second resolution: a resolution stamped "now" would equal a request
        # stamped "now", which the compute reads as resolved.
        self.request.sudo().write(
            {
                "close_requested_at": fields.Datetime.now() - timedelta(minutes=1),
                "close_request_resolved_at": fields.Datetime.now(),
            }
        )
        self._request_close()
        request = self._fresh()
        self.assertGreater(request.close_requested_at, request.close_request_resolved_at)
        self.assertTrue(request.close_request_pending)

    def test_request_never_dispatches_a_real_sms_or_email(self):
        mail_message_cls = type(self.env["mail.message"])
        with patch.object(mail_message_cls, "_send_sms") as mock_send_sms:
            with patch.object(mail_message_cls, "_send_email") as mock_send_email:
                self._request_close(reason="Klart")
        mock_send_sms.assert_not_called()
        mock_send_email.assert_not_called()
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestRequestCloseFromTenant#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected: every test errors with `AttributeError: 'maintenance.request' object has no attribute 'request_close_from_tenant'`. Summary: `0 failed, 11 error(s)`.

- [ ] **Step 3: Implement**

`models/utils/helpers.py`: replace lines 1–4 with:

```python
"""Helper functions for maintenance requests."""

import logging
import os

from markupsafe import Markup
```

Append at the end of the file:

```python
def close_request_reason_html(reason):
    """Free text for a close-request message body, or None when blank (MIM-2036).

    Escaped, then line breaks as <br>: Mina sidor renders message bodies with
    v-html, and the text is a tenant's or a handläggare's own words, so it must
    never reach the body as markup. Markup.join escapes every piece it joins.
    Whitespace-only counts as no reason at all.
    """
    text = str(reason or "").strip()
    if not text:
        return None
    return Markup("<br>").join(text.splitlines())
```

`models/maintenance.py`: in the imports, add `from datetime import timedelta` after `import json` (line 4). Add `from odoo.tools import SQL` after `from odoo.exceptions import AccessError, UserError` (line 8). Import the helper after `from .utils import validators` (line 12). Extend the constants import (lines 23–31). The result is:

```python
import urllib.parse
import uuid
import logging
import json
from datetime import timedelta

from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL

from ...onecore_api import core_api
from .handlers import HandlerFactory, BaseMaintenanceHandler
from .utils import validators
from .utils.helpers import close_request_reason_html
```

```python
from .constants import (
    SORTED_SPACES,
    SEARCH_TYPES,
    PRIORITY_OPTIONS,
    CREATION_ORIGINS,
    FORM_STATES,
    CUSTOMER_MESSAGE_TYPE,
    RECEIPT_TO_TENANT_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
    CLOSE_REQUEST_CONFLICT_PREFIX,
)
```

Insert a new section between the end of `action_acknowledge_new_customer_info` (`        self.invalidate_recordset(["has_unread_new_customer_info"])` / `        return True`, lines 782–784) and `    def _send_creation_sms(self):` (line 786):

```python
        self.invalidate_recordset(["has_unread_new_customer_info"])
        return True

    # ============================================================================
    # CLOSE REQUEST FROM TENANT (MIM-2036)
    # ============================================================================
    # The tenant only asks; an Odoo user decides — action_accept_close_request
    # or the decline wizard — and any move to Avslutad also resolves the
    # request (MaintenanceStageManager.handle_stage_change).

    def _lock_for_close_request(self):
        """Row-lock the request, then drop its cached values.

        A blocking FOR UPDATE, deliberately not lock_for_update(): that uses
        SKIP LOCKED and raises LockError, a UserError without
        CLOSE_REQUEST_CONFLICT_PREFIX, which the work-order service would turn
        into a 500. Here the second of two concurrent callers waits; under
        REPEATABLE READ it then fails with a serialization error once the first
        commits, Odoo's RPC layer retries it (odoo/service/model.py retrying),
        and the retry reads the committed request and is refused as
        already_pending.
        """
        self.ensure_one()
        self.env.cr.execute(
            SQL(
                "SELECT id FROM %s WHERE id = %s FOR UPDATE",
                SQL.identifier(self._table),
                self.id,
            )
        )
        self.invalidate_recordset()

    def _raise_close_request_conflict(self, code):
        # A code, not Swedish: the work-order service parses it into a 409 and
        # no Odoo user ever reads it.
        raise UserError(f"{CLOSE_REQUEST_CONFLICT_PREFIX}{code}")

    def request_close_from_tenant(self, reason=None):
        """The tenant asks for the case to be closed.

        Called over XML-RPC by onecore's work-order service, as its
        integration account, on the tenant's behalf. Refused — see
        _raise_close_request_conflict — when the case is already Avslutad,
        hidden from Mimer.nu, or already has a pending request.
        """
        self.ensure_one()
        self._lock_for_close_request()
        if self.stage_id.name == "Avslutad":
            self._raise_close_request_conflict("closed")
        if self.hidden_from_my_pages:
            self._raise_close_request_conflict("hidden")
        if self.close_request_pending:
            self._raise_close_request_conflict("already_pending")

        # Neutral wording, so the same body reads right in the chatter and on
        # Mina sidor.
        body = Markup("Begäran om att avsluta ärendet")
        reason_html = close_request_reason_html(reason)
        if reason_html:
            body += Markup("<br/>Orsak: ") + reason_html
        self.message_post(
            body=body,
            message_type=CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
            subtype_xmlid="mail.mt_note",
        )

        requested_at = fields.Datetime.now()
        resolved_at = self.close_request_resolved_at
        if resolved_at and requested_at <= resolved_at:
            # Datetime has second resolution and pending needs the request
            # strictly after the last resolution; asking again within the
            # second of a decline would otherwise read as already resolved.
            requested_at = resolved_at + timedelta(seconds=1)
        # sudo(): same as message_post's last_customer_message_at write — the
        # integration account need not hold write access on every field.
        self.sudo().write({"close_requested_at": requested_at})
        return True

    def _send_creation_sms(self):
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 11 tests`. Also re-run `TestCloseRequestPending`, which must still pass.

- [ ] **Step 5: Commit**

```sh
git add onecore_maintenance_extension/models/utils/helpers.py \
  onecore_maintenance_extension/models/maintenance.py \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Let the tenant request closing a case over XML-RPC (MIM-2036)

request_close_from_tenant row-locks the request, refuses closed, hidden and
already-pending cases with a close_request_conflict:<code> UserError that the
work-order service maps to 409, and posts the escaped reason.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O4: Auto-resolve on Avslutad and `action_accept_close_request`

**Files:**
- Modify: `onecore_maintenance_extension/models/services/maintenance_workflow_service.py` (`handle_stage_change`, lines 46–49)
- Modify: `onecore_maintenance_extension/models/maintenance.py` (the MIM-2036 section from O3, after `request_close_from_tenant`)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

**Interfaces:**
- Consumes:
  - `close_request_pending` (O2)
  - `request_close_from_tenant` (O3)
  - `MaintenanceStageManager._get_stage_by_name`
  - `ExternalContractorService.validate_stage_transition`, which is unchanged
- Produces:
  - Any transition to *Avslutad* writes `close_request_resolved_at = closed_date` when a request is pending
  - `maintenance.request.action_accept_close_request() -> True`

- [ ] **Step 1: Write the failing test**

Add to the imports of `test_close_request.py`:

```python
from ...models.services import FieldChangeTracker
```

Append the class:

```python
@tagged("onecore")
class TestCloseRequestResolution(CloseRequestCase):
    def setUp(self):
        super().setUp()
        self._as(self.mimer_user).request_close_from_tenant()

    def test_accept_closes_the_case_and_resolves_the_request(self):
        self.assertIs(self._as(self.internal_user).action_accept_close_request(), True)
        request = self._fresh()
        self.assertEqual(request.stage_id, self.stage_avslutad)
        self.assertFalse(request.close_request_pending)
        self.assertEqual(request.close_request_resolved_at, request.closed_date)

    def test_contractor_cannot_accept_and_the_request_stays_pending(self):
        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            self._as(self.external_user).action_accept_close_request()
        request = self._fresh()
        self.assertNotEqual(request.stage_id, self.stage_avslutad)
        self.assertTrue(request.close_request_pending)

    def test_stage_write_failing_after_the_update_leaves_the_request_pending(self):
        # Fails after super().write() — the stage and the resolution are
        # already in the database by then — so this proves the two roll back
        # together, not merely that nothing had been written yet.
        with patch.object(
            FieldChangeTracker,
            "post_change_notifications",
            side_effect=UserError("Testfel"),
        ):
            with self.assertRaisesRegex(UserError, "Testfel"):
                self._as(self.internal_user).action_accept_close_request()
        request = self._fresh()
        self.assertNotEqual(request.stage_id, self.stage_avslutad)
        self.assertFalse(request.close_request_resolved_at)
        self.assertTrue(request.close_request_pending)

    def test_accept_when_already_handled_is_refused(self):
        self._as(self.internal_user).action_accept_close_request()
        with self.assertRaisesRegex(UserError, "Begäran om avslut är redan hanterad"):
            self._as(self.internal_user).action_accept_close_request()

    def test_drag_to_avslutad_resolves_a_pending_request(self):
        self._as(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        request = self._fresh()
        self.assertFalse(request.close_request_pending)
        self.assertEqual(request.close_request_resolved_at, request.closed_date)

    def test_other_stage_changes_leave_the_request_pending(self):
        # Assigning a resource auto-moves the case to Resurs tilldelad.
        self._as(self.internal_user).write({"user_id": self.internal_user.id})
        request = self._fresh()
        self.assertEqual(request.stage_id, self._stage("Resurs tilldelad"))
        self.assertTrue(request.close_request_pending)

    def test_closing_without_a_request_stamps_nothing(self):
        other = create_maintenance_request(self.env, maintenance_team_id=self.team.id)
        other.with_user(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        self.assertFalse(other.close_request_resolved_at)

    def test_case_moved_out_of_avslutad_accepts_a_new_request(self):
        self._as(self.internal_user).action_accept_close_request()
        self._as(self.internal_user).write({"stage_id": self.stage_vantar.id})
        self.assertIs(self._as(self.mimer_user).request_close_from_tenant(), True)
        self.assertTrue(self._fresh().close_request_pending)
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestCloseRequestResolution#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected:
- `AttributeError: ... 'action_accept_close_request'` for the five accept-based tests
- `FAIL: ...test_drag_to_avslutad_resolves_a_pending_request` with `AssertionError: True is not false`
- `test_other_stage_changes_leave_the_request_pending` and `test_closing_without_a_request_stamps_nothing` pass already

- [ ] **Step 3: Implement**

`models/services/maintenance_workflow_service.py`, `handle_stage_change` lines 46–49. Replace

```python
        if new_stage.name == "Avslutad":
            updates["closed_date"] = fields.Datetime.now()
        else:
            updates["closed_date"] = False
```

with

```python
        if new_stage.name == "Avslutad":
            updates["closed_date"] = fields.Datetime.now()
            # MIM-2036: a tenant's close request cannot outlive the case being
            # closed, whether through "Avsluta ärendet" or a drag to Avslutad.
            # Same write as the stage, so a transition that fails validation
            # leaves the request pending. Applied to the whole recordset: on a
            # record without a pending request the extra stamp is inert.
            if any(r.close_request_pending for r in record):
                updates["close_request_resolved_at"] = updates["closed_date"]
        else:
            updates["closed_date"] = False
```

`models/maintenance.py`, directly after `request_close_from_tenant` (after its `return True`, before `def _send_creation_sms`):

```python
    def action_accept_close_request(self):
        """Close the case on the tenant's request ("Avsluta ärendet").

        Writes the stage as the acting user, so the workflow and the
        contractor rules in write() run unchanged: an external contractor may
        never move a case to Avslutad and is refused there, which is why the
        chatter only offers them Avslå. The resolution is not written here —
        the transition itself stamps it, in the same write.
        """
        self.ensure_one()
        if not self.close_request_pending:
            raise UserError(_("Begäran om avslut är redan hanterad."))
        closed_stage = MaintenanceStageManager(self.env)._get_stage_by_name("Avslutad")
        self.write({"stage_id": closed_stage.id})
        return True
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 8 tests`. Also run `/onecore_maintenance_extension:TestMaintenanceStageManager` to check the existing stage tests are unaffected.

- [ ] **Step 5: Commit**

```sh
git add onecore_maintenance_extension/models/services/maintenance_workflow_service.py \
  onecore_maintenance_extension/models/maintenance.py \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Resolve close requests when a case reaches Avslutad (MIM-2036)

Any transition to Avslutad stamps close_request_resolved_at in the same write.
action_accept_close_request moves the case there as the acting user, so
contractor stage rules still refuse contractors.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O5: Decline wizard

**Files:**
- Create: `onecore_maintenance_extension/models/close_request_decline_wizard.py`
- Create: `onecore_maintenance_extension/views/close_request_decline_wizard_view.xml`
- Modify: `onecore_maintenance_extension/models/__init__.py` (append after line 18, `from . import backfill_wizard`)
- Modify: `onecore_maintenance_extension/security/ir.model.access.csv` (after line 27, the backfill-wizard row)
- Modify: `onecore_maintenance_extension/__manifest__.py` (`data`, after `"views/backfill_wizard_view.xml",`)
- Modify: `onecore_maintenance_extension/models/maintenance.py` (MIM-2036 section, after `action_accept_close_request`)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

**Interfaces:**
- Consumes:
  - `_lock_for_close_request` (O3)
  - `close_request_reason_html` (O3)
  - `CLOSE_REQUEST_DECLINED_MESSAGE_TYPE` (O1)
  - MIM-2040 sender label on tenant-facing types
- Produces:
  - `maintenance.request.action_decline_close_request() -> act_window dict`
  - Transient `maintenance.close.request.decline.wizard` with `request_id` (Many2one, required) and `reason` (Text, required)
  - `action_confirm()`

- [ ] **Step 1: Write the failing test**

Add `import re` as the first line of the `test_close_request.py` import block. Then append:

```python
@tagged("onecore")
class TestCloseRequestDecline(CloseRequestCase):
    WIZARD = "maintenance.close.request.decline.wizard"

    def setUp(self):
        super().setUp()
        self._as(self.mimer_user).request_close_from_tenant()

    def _wizard(self, user, reason="Vi väntar på reservdelar."):
        return (
            self.env[self.WIZARD]
            .with_user(user)
            .create({"request_id": self.request.id, "reason": reason})
        )

    def _declines(self):
        return self._messages(CLOSE_REQUEST_DECLINED_MESSAGE_TYPE)

    def test_decline_action_opens_the_wizard_for_this_request(self):
        action = self._as(self.internal_user).action_decline_close_request()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertEqual(action["res_model"], self.WIZARD)
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"], {"default_request_id": self.request.id})

    def test_decline_action_when_already_handled_is_refused(self):
        self._wizard(self.internal_user).action_confirm()
        with self.assertRaisesRegex(UserError, "Begäran om avslut är redan hanterad"):
            self._as(self.internal_user).action_decline_close_request()

    def test_confirm_posts_the_reason_and_resolves(self):
        self._wizard(self.internal_user).action_confirm()
        decline = self._declines()
        self.assertEqual(len(decline), 1)
        self.assertIn("Vi väntar på reservdelar.", decline.body)
        self.assertEqual(decline.author_id, self.internal_user.partner_id)
        # Tenant-facing (MIM-2040): work-order shows onecore_tenant_author_name
        # for every whitelisted type except the tenant-authored ones.
        self.assertEqual(decline.onecore_tenant_author_name, "Mimer")
        request = self._fresh()
        self.assertFalse(request.close_request_pending)
        self.assertTrue(request.close_request_resolved_at)

    def test_reason_is_escaped_in_the_body(self):
        self._wizard(
            self.internal_user, reason="<script>x()</script>\nVi återkommer"
        ).action_confirm()
        body = self._declines().body
        self.assertIn("&lt;script&gt;x()&lt;/script&gt;<br>Vi återkommer", body)
        self.assertNotIn("<script", body)

    def test_whitespace_only_reason_is_refused(self):
        # required=True on the field lets whitespace through; the wizard must not.
        wizard = self._wizard(self.internal_user, reason="  \n\t ")
        with self.assertRaisesRegex(UserError, "Ange en orsak"):
            wizard.action_confirm()
        self.assertFalse(self._declines())
        self.assertTrue(self._fresh().close_request_pending)

    def test_contractor_can_decline_and_is_named_to_the_tenant(self):
        self._wizard(self.external_user).action_confirm()
        self.assertFalse(self._fresh().close_request_pending)
        # MIM-2040 labels tenant-facing messages from their author at write time.
        self.assertEqual(
            self._declines().onecore_tenant_author_name,
            "Mimers Leverantör - Test Team",
        )

    def test_confirm_after_the_case_was_closed_says_already_handled(self):
        wizard = self._wizard(self.internal_user)
        self._as(self.internal_user).action_accept_close_request()
        with self.assertRaisesRegex(
            UserError, re.escape("Begäran om avslut är redan hanterad.")
        ):
            wizard.action_confirm()
        self.assertFalse(self._declines())

    def test_second_decline_says_already_handled(self):
        first = self._wizard(self.internal_user)
        second = self._wizard(self.external_user, reason="Nej")
        first.action_confirm()
        with self.assertRaisesRegex(
            UserError, re.escape("Begäran om avslut är redan hanterad.")
        ):
            second.action_confirm()
        self.assertEqual(len(self._declines()), 1)

    def test_new_request_after_a_decline_is_pending_again(self):
        self._wizard(self.internal_user).action_confirm()
        self._as(self.mimer_user).request_close_from_tenant(reason="Snälla")
        self.assertTrue(self._fresh().close_request_pending)

    def test_decline_never_dispatches_a_real_sms_or_email(self):
        mail_message_cls = type(self.env["mail.message"])
        with patch.object(mail_message_cls, "_send_sms") as mock_send_sms:
            with patch.object(mail_message_cls, "_send_email") as mock_send_email:
                self._wizard(self.internal_user).action_confirm()
        mock_send_sms.assert_not_called()
        mock_send_email.assert_not_called()
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestCloseRequestDecline#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected: `KeyError: 'maintenance.close.request.decline.wizard'` from `self.env[self.WIZARD]`, plus `AttributeError: ... 'action_decline_close_request'`. Summary: `0 failed, 10 error(s)`.

- [ ] **Step 3: Implement**

Create `onecore_maintenance_extension/models/close_request_decline_wizard.py`:

```python
"""Decline a tenant's close request with a reason the tenant reads (MIM-2036)."""

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import clean_context

from .constants import CLOSE_REQUEST_DECLINED_MESSAGE_TYPE
from .utils.helpers import close_request_reason_html


class MaintenanceCloseRequestDeclineWizard(models.TransientModel):
    _name = "maintenance.close.request.decline.wizard"
    _description = "Avslå begäran om avslut"

    # Not readonly: the dialog is opened with default_request_id, and the web
    # client does not send readonly fields on save.
    request_id = fields.Many2one(
        "maintenance.request",
        string="Ärende",
        required=True,
        ondelete="cascade",
    )
    reason = fields.Text(
        string="Orsak",
        required=True,
        help="Visas för hyresgästen på Mina sidor.",
    )

    def action_confirm(self):
        """Post the decline and resolve the request.

        Locked and re-read first: the dialog can sit open while someone else
        declines or the case is closed from the kanban, and a stale second
        answer must not reach the tenant.
        """
        self.ensure_one()
        # The dialog's default_request_id must not leak into the message post.
        request = self.request_id.with_context(clean_context(self.env.context))
        request._lock_for_close_request()
        if not request.close_request_pending:
            raise UserError(_("Begäran om avslut är redan hanterad."))
        reason_html = close_request_reason_html(self.reason)
        if not reason_html:
            raise UserError(_("Ange en orsak till att begäran avslås."))
        # Posted as the deciding user, so MIM-2040 names the sender to the
        # tenant — "Mimers Leverantör - <resursgrupp>" when a contractor
        # declines.
        request.message_post(
            body=reason_html,
            message_type=CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
            subtype_xmlid="mail.mt_note",
        )
        request.write({"close_request_resolved_at": fields.Datetime.now()})
        return {"type": "ir.actions.act_window_close"}
```

Append to `models/__init__.py` after `from . import backfill_wizard`:

```python
from . import close_request_decline_wizard
```

`models/maintenance.py`, directly after `action_accept_close_request`:

```python
    def action_decline_close_request(self):
        """Open the Avslå dialog. Contractors may decline as well as Mimer."""
        self.ensure_one()
        if not self.close_request_pending:
            raise UserError(_("Begäran om avslut är redan hanterad."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Avslå begäran om avslut"),
            "res_model": "maintenance.close.request.decline.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_request_id": self.id},
        }
```

Create `onecore_maintenance_extension/views/close_request_decline_wizard_view.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data>
        <record id="maintenance_close_request_decline_wizard_form" model="ir.ui.view">
            <field name="name">maintenance.close.request.decline.wizard.form</field>
            <field name="model">maintenance.close.request.decline.wizard</field>
            <field name="arch" type="xml">
                <form string="Avslå begäran om avslut">
                    <sheet>
                        <field name="request_id" invisible="1" />
                        <p class="text-muted">Orsaken visas för hyresgästen på Mina sidor.</p>
                        <group>
                            <field name="reason"
                                placeholder="Till exempel: Vi väntar på reservdelar och återkommer när de har kommit." />
                        </group>
                    </sheet>
                    <footer>
                        <button name="action_confirm" type="object" string="Avslå"
                            class="btn-primary" data-hotkey="q" />
                        <button string="Avbryt" class="btn-secondary" special="cancel"
                            data-hotkey="x" />
                    </footer>
                </form>
            </field>
        </record>
    </data>
</odoo>
```

`security/ir.model.access.csv`: insert after line 27 (`access_maintenance_backfill_wizard_equipment_manager,...`). The group is `base.group_user` because external contractors imply it and may decline:

```
access_maintenance_close_request_decline_wizard_user,maintenance.close.request.decline.wizard.user,model_maintenance_close_request_decline_wizard,base.group_user,1,1,1,1
```

`__manifest__.py` `data`:

```python
        "views/backfill_wizard_view.xml",
        "views/close_request_decline_wizard_view.xml",
        "views/res_users_view.xml",
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 10 tests`. The module installs cleanly, so the view and ACL load without errors.

- [ ] **Step 5: Commit**

```sh
git add onecore_maintenance_extension/models/close_request_decline_wizard.py \
  onecore_maintenance_extension/views/close_request_decline_wizard_view.xml \
  onecore_maintenance_extension/models/__init__.py onecore_maintenance_extension/models/maintenance.py \
  onecore_maintenance_extension/security/ir.model.access.csv onecore_maintenance_extension/__manifest__.py \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Add a decline wizard for tenant close requests (MIM-2036)

Avslå opens a dialog with a required reason, shown to the tenant. Confirming
re-checks the request under a row lock, so a stale dialog cannot answer a
request that was already declined or closed.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O6: "Hyresgäst vill avsluta" badge on kanban, mobile and form

**Files:**
- Modify: `onecore_maintenance_extension/static/src/scss/mimer_styles.scss` (after `.mimer-badge-green`, lines 44–55)
- Modify: `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml` (badge column, lines 8–13)
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml`:
  - Form header fields (lines 155–161)
  - Form badge div (lines 199–204)
  - Kanban field list (line 996)
- Modify: `onecore_maintenance_extension/views/mobile_view.xml` (line 57)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

The mobile card has no badge markup of its own. `onecore_ui/static/src/views/mobile_record.xml` t-calls the same `maintenance_request_item` template, so `mobile_view.xml` only has to load the field.

**Interfaces:**
- Consumes: `close_request_pending` (O2)
- Produces:
  - `.mimer-badge-purple`
  - Badge "Hyresgäst vill avsluta" with `fa-flag-checkered`
  - `close_request_pending` loaded by the kanban, mobile and form views (the chatter in O7 reads it from the form record)

- [ ] **Step 1: Write the failing test**

Add `file_open` to the `odoo.tools` import in `test_close_request.py` (`from odoo.tools import SQL, file_open`). Then append:

```python
@tagged("onecore")
class TestCloseRequestBadge(TransactionCase):
    """The card and form can only read fields their view arch loads; a badge
    whose field is missing from the arch renders nothing and raises nothing."""

    def _arch(self, view_type):
        return self.env["maintenance.request"].get_view(view_type=view_type)["arch"]

    def _source(self, path):
        with file_open(path) as source:
            return source.read()

    def test_kanban_loads_the_pending_flag(self):
        self.assertIn('name="close_request_pending"', self._arch("kanban"))

    def test_form_loads_the_pending_flag(self):
        self.assertIn('name="close_request_pending"', self._arch("form"))

    def test_mobile_view_loads_the_pending_flag(self):
        arch = self.env.ref(
            "onecore_maintenance_extension.hr_equipment_request_view_mobile"
        ).arch
        self.assertIn('name="close_request_pending"', arch)

    def test_card_template_renders_the_purple_badge(self):
        template = self._source(
            "onecore_maintenance_extension/static/src/views/maintenance_request_item.xml"
        )
        self.assertIn("record.close_request_pending.raw_value", template)
        self.assertIn("mimer-badge-purple", template)
        self.assertIn("fa-flag-checkered", template)
        self.assertIn("Hyresgäst vill avsluta", template)

    def test_purple_badge_style_exists(self):
        scss = self._source(
            "onecore_maintenance_extension/static/src/scss/mimer_styles.scss"
        )
        self.assertIn(".mimer-badge-purple", scss)
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestCloseRequestBadge#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected: five `FAIL:` lines, each `AssertionError: '...' not found in '...'`. Summary: `5 failed, 0 error(s)`.

- [ ] **Step 3: Implement**

`static/src/scss/mimer_styles.scss`: insert after the `.mimer-badge-green` block (after line 55):

```scss
// Mimer decision purple (Material purple 50 / 300 / 900). "Hyresgäst vill
// avsluta" is the only badge that asks for a decision rather than an
// acknowledgement, so it gets a colour of its own next to the four orange
// ones, plus the fa-flag-checkered icon so colour is not the only signal
// (MIM-2036).
$mimer-purple-bg: #F3E5F5;
$mimer-purple-border: #BA68C8;
$mimer-purple-text: #4A148C;

.mimer-badge-purple {
    background: $mimer-purple-bg;
    border-color: $mimer-purple-border;
    color: $mimer-purple-text;
}
```

`static/src/views/maintenance_request_item.xml`: make it the first badge in the column (lines 8–9):

```xml
            <div class="d-flex flex-column">
                <div t-if="record.close_request_pending.raw_value">
                    <span class="mimer-badge mimer-badge-purple">
                        <i class="fa fa-flag-checkered me-1" role="img" aria-hidden="true"/>
                        Hyresgäst vill avsluta
                    </span>
                </div>
                <div t-if="record.has_unread_customer_message.raw_value">
```

`views/maintenance_views.xml`, form header fields (line 161). Add after `has_unread_customer_message`:

```xml
                    <field name="has_unread_customer_message" invisible="1" />
                    <field name="close_request_pending" invisible="1" />
                </xpath>
```

In the same form, the badge `<div>` inside `//group[1]` (lines 199–200). Add as the first child:

```xml
                    <div>
                        <div
                            class="mimer-badge mimer-badge-purple mb-3 fs-6 lh-base px-3 py-2 rounded-pill"
                            invisible="not close_request_pending">
                            <i class="fa fa-flag-checkered me-1" role="img" aria-hidden="true" />
                            <span>Hyresgäst vill avsluta</span>
                        </div>
                        <div class="mimer-badge mb-3 fs-6 lh-base px-3 py-2 rounded-pill"
                            invisible="not create_date">
```

Kanban field list (line 996):

```xml
                    <field name="has_unread_customer_message" />
                    <field name="close_request_pending" />
                    <field name="special_attention" />
```

`views/mobile_view.xml` (line 57):

```xml
        <field name="has_unread_customer_message" />
        <field name="close_request_pending" />
        <field name="special_attention" />
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 5 tests`. Then check the UI by eye:
1. Start `./run-local-odoo.sh onecore_maintenance_extension` against a local DB (never the dev cluster).
2. In `odoo-bin shell` on that DB, run `env["maintenance.request"].browse(<id>).with_user(env.ref("base.user_admin")).request_close_from_tenant("Test"); env.cr.commit()`.
3. Confirm the purple badge shows first on the kanban card, on the mobile card (narrow window) and in the form, and that the card sorts to the top of its column.

- [ ] **Step 5: Commit**

```sh
git add onecore_maintenance_extension/static/src/scss/mimer_styles.scss \
  onecore_maintenance_extension/static/src/views/maintenance_request_item.xml \
  onecore_maintenance_extension/views/maintenance_views.xml onecore_maintenance_extension/views/mobile_view.xml \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Show a purple \"Hyresgäst vill avsluta\" badge on pending cases (MIM-2036)

The badge sits first on the kanban and mobile card and in the form. Purple
sets it apart from the orange acknowledge badges, and a flag icon keeps it
readable without colour.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task O7: Chatter signal with *Avsluta ärendet* and *Avslå*

**Files:**
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js`:
  - `setup()`, lines 19–25
  - New methods before the closing `});` at line 335
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter.xml` (after the acknowledge-button xpath, lines 20–28)
- Modify: `onecore_mail_extension/static/src/tenant/tenant_message.scss` (after the `.o-mail-Message.mimer-dialog-unread` block)
- Test: `onecore_maintenance_extension/tests/models/test_close_request.py`

**Interfaces:**
- Consumes:
  - `close_request_pending` and `user_is_external_contractor` from the form record (O6; `user_is_external_contractor` is already in the form at `maintenance_views.xml:890`)
  - `action_accept_close_request` (O4)
  - `action_decline_close_request` (O5)
- Produces: a purple chatter strip on pending cases. Its "Avsluta ärendet" button is hidden for external contractors; its "Avslå" button opens the wizard. Both reload the record and the messages afterwards.

- [ ] **Step 1: Write the failing test**

Append to `test_close_request.py`:

```python
@tagged("onecore")
class TestCloseRequestChatterSignal(TransactionCase):
    """The chatter calls the model by method name from JavaScript; a rename on
    either side would fail silently in the browser. Pin the names here."""

    JS = "onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js"
    XML = "onecore_mail_extension/static/src/tenant/tenant_chatter.xml"

    def _source(self, path):
        with file_open(path) as source:
            return source.read()

    def test_chatter_calls_methods_that_exist(self):
        js = self._source(self.JS)
        for method in ("action_accept_close_request", "action_decline_close_request"):
            with self.subTest(method=method):
                self.assertIn(f'"{method}"', js)
                self.assertTrue(hasattr(self.env["maintenance.request"], method))

    def test_accept_is_hidden_for_external_contractors(self):
        js = self._source(self.JS)
        self.assertIn("user_is_external_contractor", js)
        template = self._source(self.XML)
        self.assertIn('t-if="showCloseRequestSignal()"', template)
        self.assertIn('t-if="canAcceptCloseRequest()"', template)
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
sed 's#--test-tags=onecore#--test-tags=/onecore_maintenance_extension:TestCloseRequestChatterSignal#' run_tests.sh | bash 2>&1 \
  | grep -E "FAIL:|ERROR|failed, .* error\(s\) of"
```

Expected:
- `FAIL: ...test_chatter_calls_methods_that_exist` with `AssertionError: '"action_accept_close_request"' not found in ...`
- `FAIL: ...test_accept_is_hidden_for_external_contractors`
- Summary: `2 failed, 0 error(s)`

- [ ] **Step 3: Implement**

`tenant_chatter_patch.js`, `setup()` (lines 19–25):

```js
  setup() {
    super.setup();
    this.dialogService = this.env.services.dialog;
    // MIM-1956 — guards the pill row against a second click landing while a
    // filter-triggered fetch is already in flight (see onClickLogFilter).
    this.state.onecoreLogFilterBusy = false;
    // MIM-2036 — same guard for the close-request buttons, so a double click
    // cannot send the accept twice.
    this.state.onecoreCloseRequestBusy = false;
  },
```

Insert before the patch's closing `});` (after `onClickAcknowledge`, line 334):

```js
  // MIM-2036 — "Hyresgäst vill avsluta". Deliberately not one of
  // _unreadAckSignals: it asks for a decision, not an acknowledgement, so it
  // has its own strip with two actions and is never folded into "Markera som
  // läst".
  showCloseRequestSignal() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      !!this.props.record.data.close_request_pending
    );
  },

  // External contractors may never move a case to Avslutad
  // (ExternalContractorService.validate_stage_transition), so they are only
  // offered Avslå. The server refuses them regardless; this keeps a button
  // that could never succeed off their screen.
  canAcceptCloseRequest() {
    return !this.props.record?.data?.user_is_external_contractor;
  },

  async _refreshAfterCloseRequest() {
    // Reload so the stage, the badge and close_request_pending refresh, then
    // fetch the request's new chatter message (the decline or the stage note).
    await this.props.record.load();
    await this.state?.thread?.fetchNewMessages();
  },

  async _runCloseRequestAction(callback) {
    const record = this.props.record;
    if (!record?.resId || this.state.onecoreCloseRequestBusy) {
      return;
    }
    this.state.onecoreCloseRequestBusy = true;
    try {
      // The reload afterwards would drop unsaved edits in the form. Save
      // first; a form that cannot be saved stops here with its own message.
      if ((await record.isDirty()) && !(await record.save())) {
        return;
      }
      await callback(record);
    } finally {
      this.state.onecoreCloseRequestBusy = false;
    }
  },

  onClickAcceptCloseRequest() {
    return this._runCloseRequestAction(async (record) => {
      await this.env.services.orm.call(
        "maintenance.request",
        "action_accept_close_request",
        [[record.resId]],
      );
      await this._refreshAfterCloseRequest();
    });
  },

  onClickDeclineCloseRequest() {
    return this._runCloseRequestAction(async (record) => {
      const action = await this.env.services.orm.call(
        "maintenance.request",
        "action_decline_close_request",
        [[record.resId]],
      );
      await this.env.services.action.doAction(action, {
        onClose: () => this._refreshAfterCloseRequest(),
      });
    });
  },
```

`tenant_chatter.xml`: insert after the acknowledge-button xpath (after line 28) and before the händelselogg-filter xpath. Both use `position="before"` on the same node, so declaring this one first renders the strip above the filter pills:

```xml
    <!-- MIM-2036 — "Hyresgäst vill avsluta". A decision rather than an
         acknowledgement, so it gets its own strip instead of joining the
         acknowledge button. Avsluta ärendet is hidden for external
         contractors, who may never move a case to Avslutad. -->
    <xpath expr="//div[hasclass('o-mail-Chatter-content')]" position="before">
        <div class="o-mimer-CloseRequest d-flex flex-wrap align-items-center gap-2 flex-shrink-0"
             t-if="showCloseRequestSignal()"
             role="status">
            <span class="fw-semibold">
                <i class="fa fa-flag-checkered me-1" aria-hidden="true"/>Hyresgäst vill avsluta ärendet
            </span>
            <div class="ms-auto d-flex gap-2">
                <button class="btn btn-sm o-mimer-CloseRequest-accept text-nowrap"
                        t-if="canAcceptCloseRequest()"
                        t-att-disabled="state.onecoreCloseRequestBusy"
                        t-on-click="onClickAcceptCloseRequest">
                    Avsluta ärendet
                </button>
                <button class="btn btn-sm btn-outline-secondary text-nowrap"
                        t-att-disabled="state.onecoreCloseRequestBusy"
                        t-on-click="onClickDeclineCloseRequest">
                    Avslå
                </button>
            </div>
        </div>
    </xpath>
```

`tenant_message.scss`: insert after the `.o-mail-Message.mimer-dialog-unread { ... }` block:

```scss
// MIM-2036 — "Hyresgäst vill avsluta" strip. Mirrors .mimer-badge-purple in
// onecore_maintenance_extension (Material purple 50 / 300 / 900), which this
// module does not depend on.
$mimer-close-request-bg: #F3E5F5;
$mimer-close-request-border: #BA68C8;
$mimer-close-request-text: #4A148C;

.o-mimer-CloseRequest {
    margin: 0 16px 8px;
    padding: 8px 12px;
    background-color: $mimer-close-request-bg;
    border: 0.5px solid $mimer-close-request-border;
    border-radius: 4px;
    color: $mimer-close-request-text;

    .o-mimer-CloseRequest-accept {
        background-color: $mimer-close-request-text;
        border-color: $mimer-close-request-text;
        color: #FFF;
    }
}
```

- [ ] **Step 4: Run, expect PASS**

Same command as Step 2. Expected: `0 failed, 0 error(s) of 2 tests`. Then run the whole suite with `./run_tests.sh`. Expected: `0 failed, 0 error(s)`.

Then verify in the browser, locally only (workspace `local-e2e` skill):
1. Use a pending case set up as in O6 Step 4.
2. As a Mimer handler, check the strip shows both buttons.
3. *Avslå* with an empty or whitespace-only reason is refused. With a reason it posts the decline, and the strip and badge disappear.
4. Request again from the shell. The strip returns.
5. *Avsluta ärendet* moves the case to *Avslutad*, and the strip disappears.
6. As a contractor on the case's team, only *Avslå* shows.

Stop `run-local-odoo.sh` when done.

- [ ] **Step 5: Commit**

```sh
git add onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js \
  onecore_mail_extension/static/src/tenant/tenant_chatter.xml \
  onecore_mail_extension/static/src/tenant/tenant_message.scss \
  onecore_maintenance_extension/tests/models/test_close_request.py
git commit -m "Add close-request actions to the maintenance chatter (MIM-2036)

A purple strip on cases with a pending tenant close request offers Avsluta
ärendet and Avslå. External contractors, who cannot close cases, only see
Avslå.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Findings that contradict or extend the spec/contract

1. **Reason handling:** the spec says the reason is "stripped of tags". The contract says it is HTML-escaped with newlines turned into `<br>`. The plan follows the contract (`close_request_reason_html`), and the tests assert escaped text, not stripped text.
2. **MIM-2040 adds a second classification the spec does not mention.** `EXPECTED_TENANT_FACING` and `TENANT_FACING_MESSAGE_TYPES` must include both new types, or MIM-2040's guard test fails the build. `close_request_declined` must be **True**: onecore's MIM-2040 `messageAuthor` returns `onecore_tenant_author_name || "Mimer"`, so a contractor's decline would otherwise show as "Mimer". `close_request_from_tenant` is **False**, like `from_tenant`. This matches the contract's "messageAuthor treats `close_request_from_tenant` like `from_tenant`".
3. **Odoo 19's `lock_for_update()` must not be used.** It issues `FOR UPDATE SKIP LOCKED` and raises `LockError`, a UserError without the `close_request_conflict:` prefix, so work-order would answer 500. The plan uses a plain blocking `SELECT ... FOR UPDATE`. The concurrent second call then fails with a serialization error, Odoo's RPC `retrying` re-runs it, and the retry refuses with `already_pending`. This matches the contract's wording. The actual race cannot be exercised in a TransactionCase; the test pins that the lock is taken before the checks.
4. **Datetime has second resolution.** Under the spec's formula (`requested > resolved`), a new request in the same second as a decline would read as resolved. `request_close_from_tenant` therefore bumps `close_requested_at` to `resolved_at + 1s` when needed. Same-second request plus decline still reads as resolved, which is correct.
5. **New stamp fields must go in `FieldChangeTracker.SKIP_FIELDS`**, or every request, decline and auto-resolve also posts a field-change note. The spec is silent on this.
6. **`base.user_root` (the TransactionCase uid and OdooBot) is in `group_external_contractor`.** Any superuser write to *Avslutad* is refused by the contractor rule, so tests must run as dedicated users.
7. **The mobile view has no badge markup of its own.** `onecore_ui/static/src/views/mobile_record.xml` t-calls `maintenance_request_item`, so `mobile_view.xml` only needs the field declared. Likewise, the form's existing badges live in the first `<group>`'s badge div, not in `<header>`. The plan adds the badge there, and the hidden field in `<header>`.
8. **No migration is needed.** The fields are new, stay NULL on existing rows, and the stored compute initialises itself. Version bumps are maintenance `19.0.1.0.11` → `19.0.1.0.12` and mail `19.0.1.0.1` → `19.0.1.0.2` (post-MIM-2040). The ops `odoo-module-upgrade` Job runs `-u` on every `onecore_*` module regardless of version, so the bump is convention, not a trigger.
9. **Not in the contract:**
   - `action_accept_close_request` and `action_decline_close_request` both refuse a non-pending request with the wizard's message "Begäran om avslut är redan hanterad."
   - The wizard rejects a whitespace-only reason with "Ange en orsak till att begäran avslås.", because `required=True` lets whitespace through.
   - The wizard's `request_id` is not `readonly`, because the web client does not save readonly defaults.
   - The wizard ACL goes to `base.group_user`, which contractors imply.
10. **Auto-resolve on a multi-record stage write** stamps `close_request_resolved_at` on every record in the write when any of them is pending. The stamp is inert on the others. `handle_stage_change` already receives the whole recordset.
11. **No CHANGELOG or docs convention** exists in the repo, so no entry is added. There are no JS tests in the repo; the chatter is covered by name-pinning tests plus the manual local check.

---

## onecore (`services/work-order`, `libs/types`, `core`)

Branch `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` in
`onecore/`, rebased onto `epic/mim-1983` **after** MIM-2040 has merged there.
Every line number below is from the post-MIM-2040 tree
(`origin/feature/mim-2040-tenant-facing-sender-on-work-order-messages` =
`origin/epic/mim-1983` + 3 commits). MIM-2040 does not touch `core/`, so core line
numbers equal the epic's.

Run every command from the `onecore/` root unless a step says otherwise.
`pnpm run build:libs` (or just `pnpm run build:types`) has to have run
before any service or core Jest run that imports `@onecore/types`, because the
package resolves to `libs/types/dist`.

The staff close path (`/workOrders/:id/close` in work-order, `/work-orders/:id/close` in core, and both `closeWorkOrder` adapters) is used by property-tree's inspection flow and is **not touched**. The tenant request gets its own `close-request` path (contract REVISION 1).

---

### Task C1: Read the close-request state and the new message types from Odoo

**Files:**
- Modify `services/work-order/src/services/work-order-service/schemas.ts` (lines 12-38 `WorkOrderSchema`, 40-59 `OdooWorkOrderSchema`, 74-85 `XpandWorkOrderDetailsSchema`)
- Modify `services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts` (lines 44-68 `WORK_ORDER_FIELDS`, 70-89 `MESSAGE_DOMAIN`)
- Modify `services/work-order/src/services/work-order-service/adapters/odoo-adapter/utils.ts` (line 83 `transformWorkOrder`, lines 100-114 `messageAuthor`)
- Modify `services/work-order/src/services/work-order-service/tests/factories/work-order.ts` (lines 46, 66)
- Test `services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/utils.test.ts`
- Test `services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts`

**Interfaces:**
- Consumes (Odoo): field `maintenance.request.close_request_pending` (Boolean); `mail.message.message_type` values `close_request_from_tenant`, `close_request_declined`.
- Produces: `WorkOrder.CloseRequestPending: boolean` (service `WorkOrderSchema`, and through it the service Swagger `components.schemas.WorkOrder`); `close_request_from_tenant` messages authored as the tenant; both new types returned in `Messages`.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('transformWorkOrder', ...)` in `utils.test.ts` (after the `it` that ends at line 40):

```ts
    // Mina sidor disables "Jag vill avsluta ärendet" while this is true, so a
    // tenant cannot pile up requests the handler has not answered yet.
    it('should expose a pending close request', () => {
      const result = transformWorkOrder(
        factory.odooWorkOrder.build({ close_request_pending: true })
      )

      expect(result.CloseRequestPending).toBe(true)
    })

    it('should treat a missing close_request_pending as no pending request', () => {
      const odooWorkOrder = factory.odooWorkOrder.build()
      delete odooWorkOrder.close_request_pending

      const result = transformWorkOrder(odooWorkOrder)

      expect(result.CloseRequestPending).toBe(false)
    })
```

Append inside `describe('transformMessages', ...)` in `utils.test.ts` (after the `it` that ends at line 120):

```ts
    // The integration writes the close request on the tenant's behalf, so it
    // is the tenant's message, not an outbound one. It must take the same path
    // as from_tenant. Otherwise it is labelled "Mimer" and shown as our reply.
    it('should author a close request as the tenant', () => {
      const result = transformMessages([
        factory.odooWorkOrderMessage.build({
          message_type: 'close_request_from_tenant',
          author_id: [3, 'Bostads AB Mimer, Anna Hyresgäst'],
          onecore_tenant_author_name: false,
        }),
      ])

      expect(result[0].author).toBe('Anna Hyresgäst')
      expect(result[0].messageType).toBe('close_request_from_tenant')
    })

    it('should ignore a stored sender on a close request', () => {
      const result = transformMessages([
        factory.odooWorkOrderMessage.build({
          message_type: 'close_request_from_tenant',
          author_id: [3, 'Bostads AB Mimer, Anna Hyresgäst'],
          onecore_tenant_author_name: 'Mimer',
        }),
      ])

      expect(result[0].author).toBe('Anna Hyresgäst')
    })

    // A declined request is the handler answering the tenant: outbound, so
    // it carries the sender Odoo stored, like any other reply.
    it('should use the stored sender on a declined close request', () => {
      const result = transformMessages([
        factory.odooWorkOrderMessage.build({
          message_type: 'close_request_declined',
          author_id: [7, 'Bostads AB Mimer, Sebastian Handläggare'],
          onecore_tenant_author_name: 'Mimer',
        }),
      ])

      expect(result[0].author).toBe('Mimer')
    })
```

Append inside `describe('odoo-adapter message domain', ...)` in `index.test.ts`, just before its closing `})` on line 454:

```ts

  // Both halves of a close request belong in the tenant's thread: their own
  // request echoed back, and the handler's reason when it is declined.
  it('includes both close-request message types in the Mina sidor allowlist', async () => {
    odooMock.searchRead
      .mockResolvedValueOnce([]) // maintenance.request
      .mockResolvedValueOnce([]) // mail.message

    await getWorkOrdersByContactCode('P123456')

    const messageCall = odooMock.searchRead.mock.calls.find(
      (call: unknown[]) => call[0] === 'mail.message'
    )
    expect(messageCall).toBeDefined()
    const domain = messageCall![1] as unknown[][]
    const messageTypeClause = domain.find(
      (clause) => clause[0] === 'message_type'
    )
    expect(messageTypeClause![2] as string[]).toEqual(
      expect.arrayContaining([
        'close_request_from_tenant',
        'close_request_declined',
      ])
    )
  })

  it('reads close_request_pending from maintenance.request', async () => {
    odooMock.searchRead
      .mockResolvedValueOnce([]) // maintenance.request
      .mockResolvedValueOnce([]) // mail.message

    await getWorkOrdersByContactCode('P123456')

    const workOrderCall = odooMock.searchRead.mock.calls.find(
      (call: unknown[]) => call[0] === 'maintenance.request'
    )
    expect(workOrderCall).toBeDefined()
    expect(workOrderCall![2] as string[]).toContain('close_request_pending')
  })
```

- [ ] **Step 2: Run them, expect FAIL**

```sh
pnpm run build:types
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/adapters/odoo-adapter/utils.test.ts
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts -t 'message domain'
```

Expected: `utils.test.ts` does not compile. ts-jest reports
`Property 'CloseRequestPending' does not exist on type '...WorkOrder'` and
`Object literal may only specify known properties, and 'close_request_pending' does not exist`.
In `index.test.ts`, the two new tests fail. The first fails because
`expect.arrayContaining(['close_request_from_tenant', 'close_request_declined'])`
does not match the allowlist. The second fails with
`Expected value: "close_request_pending"` not contained in `WORK_ORDER_FIELDS`.

- [ ] **Step 3: Implement**

`schemas.ts`: in `WorkOrderSchema`, after line 28 (`HiddenFromMyPages: z.boolean().optional(),`) insert:

```ts
  // True while the tenant's request to close the case awaits a decision in Odoo.
  CloseRequestPending: z.boolean(),
```

In `OdooWorkOrderSchema`, after line 51 (`master_key: z.boolean().optional(),`) insert:

```ts
  close_request_pending: z.boolean().optional(),
```

In `XpandWorkOrderDetailsSchema`'s `.omit({...})`, after line 78 (`HiddenFromMyPages: true,`) insert:

```ts
  CloseRequestPending: true, // Xpand work orders cannot carry a close request
```

`adapters/odoo-adapter/index.ts`: in `WORK_ORDER_FIELDS`, after line 67 (`'maintenance_unit_caption',`) insert:

```ts
  'close_request_pending',
```

In `MESSAGE_DOMAIN`, after line 77 (`'from_tenant',`) insert:

```ts
      // The tenant's close request echoed back into their thread, and the
      // handler's reason when it is declined. Neither is tenant_-prefixed, so
      // Odoo sends no SMS/e-post for them.
      'close_request_from_tenant',
      'close_request_declined',
```

`adapters/odoo-adapter/utils.ts`: after line 83 (`HiddenFromMyPages: odooWorkOrder.hidden_from_my_pages || false,`) insert:

```ts
    CloseRequestPending: odooWorkOrder.close_request_pending || false,
```

Replace lines 100-114 (the comment above `messageAuthor` and the function) with:

```ts
// Message types the tenant is the author of: what they wrote themselves, and
// the close request the integration writes on their behalf. Odoo stores no
// tenant-facing sender on these, and Mina sidor labels them "Du".
const TENANT_AUTHORED_MESSAGE_TYPES = ['from_tenant', 'close_request_from_tenant']

// The sender Mina sidor prints beside a message. Odoo decides it when the
// message is written and stores it on the message itself — whether the author
// was one of us or an external contractor, and which resource group they
// answered for, is knowable there and nowhere else, so it is carried across
// rather than derived here.
const messageAuthor = (message: OdooWorkOrderMessage): string => {
  if (TENANT_AUTHORED_MESSAGE_TYPES.includes(message.message_type)) {
    return last(message.author_id[1].split(', ')) ?? '' // author name is in format "YourCompany, Mitchell Admin"
  }
  // Everything else is outbound. Falling back to author_id here would put a
  // handläggare's name in front of a tenant, which is the bug this fixes.
  return message.onecore_tenant_author_name || TENANT_AUTHOR_FALLBACK
}
```

`tests/factories/work-order.ts`: after line 46 (`HiddenFromMyPages: false,` in `WorkOrderFactory`) insert `  CloseRequestPending: false,`. After line 66 (`hidden_from_my_pages: false,` in `OdooWorkOrderFactory`) insert `    close_request_pending: false,`.

- [ ] **Step 4: Run, expect PASS**

```sh
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests
pnpm --filter @onecore/work-order run typecheck
```

Expected: all suites green (existing route tests build `factory.workOrder`, which now includes `CloseRequestPending`), `tsc --noEmit` clean.

- [ ] **Step 5: Commit**

```sh
pnpm exec prettier --write services/work-order/src/services/work-order-service/schemas.ts services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts services/work-order/src/services/work-order-service/adapters/odoo-adapter/utils.ts services/work-order/src/services/work-order-service/tests/factories/work-order.ts services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/utils.test.ts services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts
git add services/work-order
git commit -m "MIM-2036: read close-request state and messages from Odoo

Fetch close_request_pending on maintenance.request and expose it as
CloseRequestPending, let close_request_from_tenant and
close_request_declined through MESSAGE_DOMAIN, and author a close request
as the tenant, the same way as from_tenant.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task C2: `requestCloseWorkOrder` and `CloseRequestConflictError` in the Odoo adapter

**Files:**
- Modify `services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts` (insert after line 787, the end of the unchanged `closeWorkOrder`)
- Test `services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts` (lines 3-9 `odooMock`, 26-32 imports, new `describe` at end of file)

**Interfaces:**
- Consumes (Odoo RPC): `maintenance.request.request_close_from_tenant(self, reason=None) -> True`. A refusal is a `UserError` with the message `close_request_conflict:<already_pending|closed|hidden>…`. On `/xmlrpc/2` (the endpoint odoo-await uses) Odoo sends it as fault code 2 with `faultString = str(e)` (`odoo/addons/rpc/controllers/xmlrpc.py` `xmlrpc_handle_exception_int`), and the `xmlrpc` client rejects with `new Error('XML-RPC fault: ' + faultString)`.
- Produces: `export const requestCloseWorkOrder(workOrderId: number, reason?: string): Promise<void>`; `export class CloseRequestConflictError extends Error { reason: 'already_pending' | 'closed' | 'hidden' }`; `export type CloseRequestConflictReason`.

- [ ] **Step 1: Write the failing tests**

In `index.test.ts`, add `execute_kw` to the mock (replace lines 3-9):

```ts
const odooMock = {
  connect: jest.fn(),
  create: jest.fn(),
  execute_kw: jest.fn(),
  search: jest.fn(),
  searchRead: jest.fn(),
  update: jest.fn(),
}
```

Replace the import block at lines 26-32:

```ts
import {
  CloseRequestConflictError,
  createInspectionWorkOrders,
  createWorkOrder,
  getMaintenanceTeams,
  getWorkOrderById,
  getWorkOrdersByContactCode,
  requestCloseWorkOrder,
} from '../../../adapters/odoo-adapter'
```

Append at the end of the file:

```ts

describe('odoo-adapter requestCloseWorkOrder', () => {
  // What the xmlrpc client rejects with when Odoo answers with a fault. On
  // /xmlrpc/2, Odoo sends a UserError as fault code 2 with str(e) as faultString.
  const xmlRpcFault = (faultString: string) =>
    Object.assign(new Error(`XML-RPC fault: ${faultString}`), {
      faultCode: 2,
      faultString,
    })

  beforeEach(() => {
    jest.clearAllMocks()
    odooMock.connect.mockResolvedValue(undefined)
    odooMock.execute_kw.mockResolvedValue(true)
  })

  it('asks Odoo without a reason when the tenant gave none', async () => {
    await requestCloseWorkOrder(13)

    expect(odooMock.execute_kw).toHaveBeenCalledWith(
      'maintenance.request',
      'request_close_from_tenant',
      [[13], {}]
    )
  })

  it('passes the tenant reason as a keyword argument', async () => {
    await requestCloseWorkOrder(13, 'Tvättmaskinen fungerar igen')

    expect(odooMock.execute_kw).toHaveBeenCalledWith(
      'maintenance.request',
      'request_close_from_tenant',
      [[13], { reason: 'Tvättmaskinen fungerar igen' }]
    )
  })

  it('does not send an empty reason', async () => {
    await requestCloseWorkOrder(13, '')

    expect(odooMock.execute_kw).toHaveBeenCalledWith(
      'maintenance.request',
      'request_close_from_tenant',
      [[13], {}]
    )
  })

  it.each(['already_pending', 'closed', 'hidden'] as const)(
    'throws CloseRequestConflictError when Odoo refuses with %s',
    async (reason) => {
      odooMock.execute_kw.mockRejectedValue(
        xmlRpcFault(`close_request_conflict:${reason}`)
      )

      await expect(requestCloseWorkOrder(13)).rejects.toThrow(
        CloseRequestConflictError
      )
      await expect(requestCloseWorkOrder(13)).rejects.toMatchObject({
        reason,
      })
    }
  )

  // Only the prefix and the reason code are the contract with Odoo. Whatever
  // text follows them is for people and may change.
  it('recognises the refusal when Odoo appends human-readable text', async () => {
    odooMock.execute_kw.mockRejectedValue(
      xmlRpcFault('close_request_conflict:closed Ärendet är redan avslutat.')
    )

    await expect(requestCloseWorkOrder(13)).rejects.toMatchObject({
      name: 'CloseRequestConflictError',
      reason: 'closed',
    })
  })

  it('rethrows any other Odoo fault unchanged', async () => {
    const fault = xmlRpcFault(
      'Traceback (most recent call last):\npsycopg2.errors.SerializationFailure'
    )
    odooMock.execute_kw.mockRejectedValue(fault)

    await expect(requestCloseWorkOrder(13)).rejects.toBe(fault)
  })

  it('rethrows a conflict prefix with a reason it does not know', async () => {
    const fault = xmlRpcFault('close_request_conflict:archived')
    odooMock.execute_kw.mockRejectedValue(fault)

    await expect(requestCloseWorkOrder(13)).rejects.toBe(fault)
  })

  it('rethrows when Odoo cannot be reached', async () => {
    const connectionError = new Error('connect ECONNREFUSED 127.0.0.1:8069')
    odooMock.connect.mockRejectedValue(connectionError)

    await expect(requestCloseWorkOrder(13)).rejects.toBe(connectionError)
    expect(odooMock.execute_kw).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts -t 'requestCloseWorkOrder'
```

Expected: the file does not compile.
`Module '"../../../adapters/odoo-adapter"' has no exported member 'CloseRequestConflictError'`
and `... 'requestCloseWorkOrder'`.

- [ ] **Step 3: Implement**

In `adapters/odoo-adapter/index.ts`, insert after line 787 (the closing `}` of `closeWorkOrder`, which stays unchanged) and before `export const addMessageToWorkOrder`:

```ts

// Odoo refuses a tenant's close request with a UserError whose message is this
// prefix followed by a reason code (onecore_maintenance_extension,
// request_close_from_tenant). The prefix and the code are the contract. Any
// text after them is for people. An unknown code is not treated as a
// conflict: it means the two sides have drifted, and should surface as a
// failure rather than a quiet 409.
const CLOSE_REQUEST_CONFLICT_PATTERN = /close_request_conflict:(\w+)/

const CloseRequestConflictReasonSchema = z.enum([
  'already_pending', // a request is already waiting for a decision
  'closed', // the work order has reached Avslutad
  'hidden', // the work order is hidden from Mina sidor
])

export type CloseRequestConflictReason = z.infer<
  typeof CloseRequestConflictReasonSchema
>

export class CloseRequestConflictError extends Error {
  readonly reason: CloseRequestConflictReason

  constructor(reason: CloseRequestConflictReason) {
    super(`Close request refused by Odoo: ${reason}`)
    this.name = 'CloseRequestConflictError'
    this.reason = reason
  }
}

const parseCloseRequestConflict = (
  err: unknown
): CloseRequestConflictReason | undefined => {
  if (!(err instanceof Error)) return undefined
  const match = err.message.match(CLOSE_REQUEST_CONFLICT_PATTERN)
  const parsed = CloseRequestConflictReasonSchema.safeParse(match?.[1])
  return parsed.success ? parsed.data : undefined
}

/**
 * Records, on the tenant's behalf, that they want the work order closed. It
 * does not close anything: Odoo posts a close_request_from_tenant message and
 * flags the request, and whoever handles the case accepts or declines it.
 * Throws CloseRequestConflictError when Odoo refuses (already pending, closed
 * or hidden). Any other failure is rethrown unchanged.
 */
export const requestCloseWorkOrder = async (
  workOrderId: number,
  reason?: string
): Promise<void> => {
  try {
    await odoo.connect()

    // execute_kw params are [args, kwargs]. The reason goes as a keyword so
    // an omitted one falls back to Odoo's reason=None default.
    await odoo.execute_kw('maintenance.request', 'request_close_from_tenant', [
      [workOrderId],
      reason ? { reason } : {},
    ])
  } catch (err) {
    const conflictReason = parseCloseRequestConflict(err)
    if (conflictReason) {
      logger.info(
        { workOrderId, reason: conflictReason },
        'odoo-adapter.requestCloseWorkOrder: refused by Odoo'
      )
      throw new CloseRequestConflictError(conflictReason)
    }
    logger.error({ err }, 'odoo-adapter.requestCloseWorkOrder')
    throw err
  }
}
```

(`z` and `logger` are already imported at lines 4-5.)

- [ ] **Step 4: Run, expect PASS**

```sh
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts
pnpm --filter @onecore/work-order run typecheck
```

- [ ] **Step 5: Commit**

```sh
pnpm exec prettier --write services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts services/work-order/src/services/work-order-service/tests/adapters/odoo-adapter/index.test.ts
git add services/work-order
git commit -m "MIM-2036: add requestCloseWorkOrder to the Odoo adapter

Call maintenance.request.request_close_from_tenant with an optional
reason, and turn Odoo's close_request_conflict:<reason> refusals into a
typed CloseRequestConflictError. Every other fault is rethrown unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task C3: Shared request schema and the work-order `close-request` route (200 / 400 / 409 / 500)

**Files:**
- Modify `libs/types/src/work-order/schema.ts` (append after line 40)
- Modify `libs/types/src/work-order/types.ts` (lines 2-8 imports, append after line 22)
- Modify `services/work-order/src/services/work-order-service/schemas.ts` (re-export block lines 195-200, type re-export block lines 237-241)
- Modify `services/work-order/src/services/work-order-service/index.ts` (imports lines 5-20; insert a new route between line 1663, the end of the unchanged `/close` handler, and line 1664, the closing `}` of `routes`)
- Test `services/work-order/src/services/work-order-service/tests/index.test.ts` (insert a new `describe` after line 325, the end of the unchanged `/close` describe)
- Create/Test `services/work-order/src/services/work-order-service/tests/close-request.test.ts`

The staff `POST (.*)/workOrders/:workOrderId/close` route and `odooAdapter.closeWorkOrder`
stay exactly as they are. property-tree's inspection flow depends on them.

**Interfaces:**
- Consumes: `requestCloseWorkOrder`, `CloseRequestConflictError` (C2).
- Produces: `CloseWorkOrderRequestSchema = z.object({ reason: z.string().optional() })` and type `CloseWorkOrderRequest` in `@onecore/types`. Route `POST (.*)/workOrders/:workOrderId/close-request` with body `{ reason?: string }` → `200 { message }`, `400 { error: [...] }`, `409 { error: 'close-request-conflict', reason }`, `500 { error }`.

- [ ] **Step 1: Write the failing tests**

In `tests/index.test.ts`, insert after line 325 (the closing `})` of `describe('POST /workOrders/:workOrderId/close', ...)`, which stays unchanged):

```ts

  describe('POST /workOrders/:workOrderId/close-request', () => {
    const workOrderId = 13
    let requestCloseSpy: jest.SpyInstance

    beforeEach(() => {
      requestCloseSpy = jest
        .spyOn(odooAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue(undefined)
      requestCloseSpy.mockClear()
    })

    it('forwards a close request without a reason', async () => {
      const res = await request(app.callback()).post(
        `/api/workOrders/${workOrderId}/close-request`
      )

      expect(res.status).toBe(200)
      expect(res.body.message).toBeDefined()
      expect(requestCloseSpy).toHaveBeenCalledWith(workOrderId, undefined)
    })

    it('forwards the reason the tenant gave', async () => {
      const res = await request(app.callback())
        .post(`/api/workOrders/${workOrderId}/close-request`)
        .send({ reason: 'Felet har försvunnit' })

      expect(res.status).toBe(200)
      expect(requestCloseSpy).toHaveBeenCalledWith(
        workOrderId,
        'Felet har försvunnit'
      )
    })

    it('returns 409 with the reason when Odoo refuses the request', async () => {
      requestCloseSpy.mockRejectedValue(
        new odooAdapter.CloseRequestConflictError('already_pending')
      )

      const res = await request(app.callback()).post(
        `/api/workOrders/${workOrderId}/close-request`
      )

      expect(res.status).toBe(409)
      expect(res.body).toMatchObject({
        error: 'close-request-conflict',
        reason: 'already_pending',
      })
    })

    it('returns 500 when the request fails for any other reason', async () => {
      requestCloseSpy.mockRejectedValue(new Error('Odoo unreachable'))

      const res = await request(app.callback()).post(
        `/api/workOrders/${workOrderId}/close-request`
      )

      expect(res.status).toBe(500)
      expect(res.body.error).toBe('Odoo unreachable')
    })

    it('returns 400 when the reason is not a string', async () => {
      const res = await request(app.callback())
        .post(`/api/workOrders/${workOrderId}/close-request`)
        .send({ reason: 42 })

      expect(res.status).toBe(400)
      expect(requestCloseSpy).not.toHaveBeenCalled()
    })
  })
```

Create `tests/close-request.test.ts`. The real route runs on top of the real adapter, with only odoo-await
stubbed, so an Odoo fault is followed all the way to the HTTP status that core receives:

```ts
import request from 'supertest'
import KoaRouter from '@koa/router'
import Koa from 'koa'
import bodyParser from 'koa-bodyparser'

// Stands in for Odoo's XML-RPC endpoint. The route and the adapter above it are
// the real ones, so this covers how an Odoo refusal becomes the status core
// sees.
const odooMock = {
  connect: jest.fn(),
  execute_kw: jest.fn(),
}

jest.mock('odoo-await', () => {
  return jest.fn().mockImplementation(() => odooMock)
})

jest.mock('@onecore/utilities', () => ({
  logger: {
    info: jest.fn(),
    error: jest.fn(),
    warn: jest.fn(),
  },
  generateRouteMetadata: jest.fn(() => ({})),
}))

import { routes } from '../index'

// What the xmlrpc client rejects with when Odoo answers with a fault. On
// /xmlrpc/2, Odoo sends a UserError as fault code 2 with str(e) as faultString.
const xmlRpcFault = (faultString: string) =>
  Object.assign(new Error(`XML-RPC fault: ${faultString}`), {
    faultCode: 2,
    faultString,
  })

const app = new Koa()
const router = new KoaRouter()
routes(router)
app.use(bodyParser())
app.use(router.routes())

describe('POST /workOrders/:workOrderId/close-request against Odoo', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    odooMock.connect.mockResolvedValue(undefined)
    odooMock.execute_kw.mockResolvedValue(true)
  })

  it('calls request_close_from_tenant without a reason when the body has none', async () => {
    const res = await request(app.callback()).post(
      '/api/workOrders/13/close-request'
    )

    expect(res.status).toBe(200)
    expect(odooMock.execute_kw).toHaveBeenCalledWith(
      'maintenance.request',
      'request_close_from_tenant',
      [[13], {}]
    )
  })

  it('calls request_close_from_tenant with the reason from the body', async () => {
    const res = await request(app.callback())
      .post('/api/workOrders/13/close-request')
      .send({ reason: 'Det fungerar igen' })

    expect(res.status).toBe(200)
    expect(odooMock.execute_kw).toHaveBeenCalledWith(
      'maintenance.request',
      'request_close_from_tenant',
      [[13], { reason: 'Det fungerar igen' }]
    )
  })

  it('answers 409, not 500, when Odoo refuses with a close_request_conflict fault', async () => {
    odooMock.execute_kw.mockRejectedValue(
      xmlRpcFault(
        'close_request_conflict:already_pending Det finns redan en begäran.'
      )
    )

    const res = await request(app.callback()).post(
      '/api/workOrders/13/close-request'
    )

    expect(res.status).toBe(409)
    expect(res.body).toMatchObject({
      error: 'close-request-conflict',
      reason: 'already_pending',
    })
  })

  it('answers 500 for any other Odoo fault', async () => {
    odooMock.execute_kw.mockRejectedValue(
      xmlRpcFault(
        'Traceback (most recent call last):\npsycopg2.errors.SerializationFailure'
      )
    )

    const res = await request(app.callback()).post(
      '/api/workOrders/13/close-request'
    )

    expect(res.status).toBe(500)
  })

  it('answers 500 when Odoo cannot be reached', async () => {
    odooMock.connect.mockRejectedValue(
      new Error('connect ECONNREFUSED 127.0.0.1:8069')
    )

    const res = await request(app.callback()).post(
      '/api/workOrders/13/close-request'
    )

    expect(res.status).toBe(500)
    expect(odooMock.execute_kw).not.toHaveBeenCalled()
  })

  it('answers 400 and does not call Odoo when the reason is not a string', async () => {
    const res = await request(app.callback())
      .post('/api/workOrders/13/close-request')
      .send({ reason: 42 })

    expect(res.status).toBe(400)
    expect(odooMock.execute_kw).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run them, expect FAIL**

```sh
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/index.test.ts -t 'close-request'
pnpm --filter @onecore/work-order exec jest src/services/work-order-service/tests/close-request.test.ts
```

Expected: every new case gets `404`, because no `/close-request` route exists yet.
The existing `/close` test still passes.

- [ ] **Step 3: Implement**

`libs/types/src/work-order/schema.ts`: append after line 40:

```ts

// Tenant → Odoo, via core and the work-order service: asks the handler to
// close a work order. Odoo decides. The reason is optional free text shown to
// the handler in the chatter.
export const CloseWorkOrderRequestSchema = z.object({
  reason: z.string().optional(),
})
```

`libs/types/src/work-order/types.ts`: add `CloseWorkOrderRequestSchema,` to the import list (lines 2-8, alphabetically first) and append:

```ts
export type CloseWorkOrderRequest = z.infer<typeof CloseWorkOrderRequestSchema>
```

Then rebuild the library so the service and core resolve the new export:

```sh
pnpm run build:types
```

`services/work-order/src/services/work-order-service/schemas.ts`: in the `@onecore/types` re-export block (lines 195-200), add `CloseWorkOrderRequestSchema,` after `CreateInspectionWorkOrdersResponseSchema,`. In the `export type { ... } from '@onecore/types'` block (lines 237-241), add `CloseWorkOrderRequest,`.

`services/work-order/src/services/work-order-service/index.ts`: add `CloseWorkOrderRequestSchema,` as the first name in the `./schemas` import (line 6). Insert between line 1663 (`  })`, the end of the unchanged `/close` handler) and line 1664 (`}`):

```ts

  /**
   * @swagger
   * /workOrders/{workOrderId}/close-request:
   *   post:
   *     summary: Request, on the tenant's behalf, that a work order be closed
   *     tags:
   *       - Work Order Service
   *     description: |
   *       Records that the tenant wants the work order closed. Nothing is closed
   *       here: Odoo posts a close_request_from_tenant message and flags the
   *       request, and whoever handles the case accepts or declines it. Staff
   *       who close a work order themselves use /workOrders/{workOrderId}/close.
   *     parameters:
   *       - in: path
   *         name: workOrderId
   *         required: true
   *         schema:
   *           type: string
   *         description: The Odoo id of the work order.
   *     requestBody:
   *       required: false
   *       content:
   *         application/json:
   *           schema:
   *             type: object
   *             properties:
   *               reason:
   *                 type: string
   *                 description: Optional reason from the tenant, shown to the handler.
   *                 example: The washing machine works again.
   *     responses:
   *       '200':
   *         description: Close request recorded in Odoo.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 message:
   *                   type: string
   *                   example: Close requested for work order with ID {workOrderId}
   *                 metadata:
   *                   type: object
   *                   description: Route metadata
   *       '400':
   *         description: The request body is malformed.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 error:
   *                   type: array
   *                   items:
   *                     type: object
   *                 metadata:
   *                   type: object
   *                   description: Route metadata
   *       '409':
   *         description: Odoo refused the request. One is already pending, the work order is closed, or it is hidden from Mina sidor.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 error:
   *                   type: string
   *                   example: close-request-conflict
   *                 reason:
   *                   type: string
   *                   enum: [already_pending, closed, hidden]
   *                 metadata:
   *                   type: object
   *                   description: Route metadata
   *       '500':
   *         description: Internal server error. Odoo could not be reached or failed.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 error:
   *                   type: string
   *                   example: Internal server error
   *                 metadata:
   *                   type: object
   *                   description: Route metadata
   *     security:
   *       - bearerAuth: []
   */
  router.post('(.*)/workOrders/:workOrderId/close-request', async (ctx) => {
    const metadata = generateRouteMetadata(ctx)
    const { workOrderId } = ctx.params

    try {
      // An empty POST has no body at all. That is a request without a reason.
      const { reason } = CloseWorkOrderRequestSchema.parse(
        ctx.request.body ?? {}
      )

      await odooAdapter.requestCloseWorkOrder(parseInt(workOrderId, 10), reason)

      ctx.status = 200
      ctx.body = {
        message: `Close requested for work order with ID ${workOrderId}`,
        ...metadata,
      }
    } catch (error: unknown) {
      if (error instanceof z.ZodError) {
        ctx.status = 400
        ctx.body = {
          error: error.issues.map(({ message, path }) => ({ message, path })),
          ...metadata,
        }
        return
      }

      // Odoo said no, for a reason the tenant can be told about. This is an
      // answer, not a failure.
      if (error instanceof odooAdapter.CloseRequestConflictError) {
        ctx.status = 409
        ctx.body = {
          error: 'close-request-conflict',
          reason: error.reason,
          ...metadata,
        }
        return
      }

      logger.error({ err: error }, 'work-order-service.requestCloseWorkOrder')
      ctx.status = 500
      ctx.body = {
        error: error instanceof Error ? error.message : 'Internal server error',
        ...metadata,
      }
    }
  })
```

(`z` and `logger` are already imported at lines 2-3. Koa-router matches
`/close` and `/close-request` separately, because a path segment has to match
exactly.)

- [ ] **Step 4: Run, expect PASS**

```sh
pnpm --filter @onecore/work-order exec jest
pnpm --filter @onecore/work-order run typecheck
pnpm --filter @onecore/types run typecheck
```

The unchanged `POST /workOrders/:workOrderId/close` test must still pass.

- [ ] **Step 5: Commit**

```sh
pnpm exec prettier --write libs/types/src/work-order/schema.ts libs/types/src/work-order/types.ts services/work-order/src/services/work-order-service/schemas.ts services/work-order/src/services/work-order-service/index.ts services/work-order/src/services/work-order-service/tests/index.test.ts services/work-order/src/services/work-order-service/tests/close-request.test.ts
git add libs/types services/work-order
git commit -m "MIM-2036: add a tenant close-request route to the work-order service

POST /workOrders/:id/close-request asks Odoo to record a close request
with an optional reason. Odoo refusals answer 409 with the reason,
malformed bodies 400, and other failures 500. The staff close route is
unchanged. The request body schema is shared with core through
@onecore/types.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task C4: Regenerate core's work-order types and add the core adapter `requestCloseWorkOrder`

**Files:**
- Modify (generated, never by hand) `core/src/adapters/work-order-adapter/generated/api-types.ts`
- Modify `core/src/adapters/work-order-adapter/index.ts` (append after line 579, the end of the unchanged `closeWorkOrder`, which is the last line of the file)
- Modify `core/test/factories/work-order-external.ts` (after line 30)
- Test `core/src/adapters/tests/work-order-adapter.test.ts` (insert a new `describe` after line 346, the end of the unchanged `closeWorkOrder` describe)

**Interfaces:**
- Consumes: the work-order Swagger from C1 + C3 (`WorkOrder.CloseRequestPending`, new path `/workOrders/{workOrderId}/close-request`).
- Produces: `requestCloseWorkOrder(workOrderId: string, reason?: string): Promise<AdapterResult<null, 'conflict' | 'unknown'>>`.

- [ ] **Step 1: Regenerate the types (needed before the typed call can be written)**

```sh
pnpm --filter @onecore/work-order run dev:init     # creates services/work-order/.env if missing
pnpm --filter @onecore/work-order run dev          # run in the background; listens on :5070
curl -sf http://localhost:5070/swagger.json > /dev/null && echo up   # no Odoo/Xpand needed for swagger.json
cd core && pnpm generate-types:work-order && cd ..
# stop the work-order dev process you started (kill its PID / Ctrl-C) before continuing
git diff --stat core/src/adapters/work-order-adapter/generated/api-types.ts
```

Check that the diff adds only two things. First, a new `'/workOrders/{workOrderId}/close-request'`
path with `requestBody?` `'application/json': { reason?: string }` and responses
`200` (`message?: string`), `400`, `409` (`reason?: 'already_pending' | 'closed' | 'hidden'`)
and `500`. Second, `CloseRequestPending: boolean` on `components.schemas.WorkOrder`, right after
`HiddenFromMyPages?: boolean`. `'/workOrders/{workOrderId}/close'`, `XpandWorkOrder` and
`XpandWorkOrderDetails` must not change. Anything else in the diff means the running service
is not the C3 tree: stop, fix, regenerate.

- [ ] **Step 2: Write the failing tests**

In `core/test/factories/work-order-external.ts`, after line 30 (`UseMasterKey: false,`), insert `  CloseRequestPending: false,`. After regeneration the field is required, so every suite that builds `externalOdooWorkOrder` fails to compile without it.

In `core/src/adapters/tests/work-order-adapter.test.ts`, insert after line 346 (the closing `})` of the unchanged `describe(workOrderAdapter.closeWorkOrder, ...)`):

```ts

  describe(workOrderAdapter.requestCloseWorkOrder, () => {
    it('sends an empty body when no reason is given', async () => {
      let received: unknown
      mockServer.use(
        http.post(
          `${config.workOrderService.url}/workOrders/1/close-request`,
          async ({ request }) => {
            received = await request.json()
            return HttpResponse.json(
              { message: 'Close requested for work order with ID 1' },
              { status: 200 }
            )
          }
        )
      )

      const result = await workOrderAdapter.requestCloseWorkOrder('1')

      expect(result).toEqual({ ok: true, data: null })
      expect(received).toEqual({})
    })

    it('forwards the reason in the body', async () => {
      let received: unknown
      mockServer.use(
        http.post(
          `${config.workOrderService.url}/workOrders/1/close-request`,
          async ({ request }) => {
            received = await request.json()
            return HttpResponse.json(
              { message: 'Close requested for work order with ID 1' },
              { status: 200 }
            )
          }
        )
      )

      const result = await workOrderAdapter.requestCloseWorkOrder(
        '1',
        'Felet har försvunnit'
      )

      expect(result.ok).toBe(true)
      expect(received).toEqual({ reason: 'Felet har försvunnit' })
    })

    it('returns conflict when the service answers 409', async () => {
      mockServer.use(
        http.post(
          `${config.workOrderService.url}/workOrders/1/close-request`,
          () =>
            HttpResponse.json(
              { error: 'close-request-conflict', reason: 'already_pending' },
              { status: 409 }
            )
        )
      )

      const result = await workOrderAdapter.requestCloseWorkOrder('1')

      expect(result).toEqual({ ok: false, err: 'conflict' })
    })

    it('returns unknown when the service fails', async () => {
      mockServer.use(
        http.post(
          `${config.workOrderService.url}/workOrders/1/close-request`,
          () => new HttpResponse(null, { status: 500 })
        )
      )

      const result = await workOrderAdapter.requestCloseWorkOrder('1')

      expect(result).toEqual({ ok: false, err: 'unknown' })
    })
  })
```

- [ ] **Step 3: Run it, expect FAIL**

```sh
pnpm --filter @onecore/core exec jest src/adapters/tests/work-order-adapter.test.ts -t 'requestCloseWorkOrder'
```

Expected: the file does not compile.
`Property 'requestCloseWorkOrder' does not exist on type 'typeof import(".../work-order-adapter")'`.

- [ ] **Step 4: Implement**

Append to `core/src/adapters/work-order-adapter/index.ts`, after line 579:

```ts

export const requestCloseWorkOrder = async (
  workOrderId: string,
  reason?: string
): Promise<AdapterResult<null, 'conflict' | 'unknown'>> => {
  try {
    const fetchResponse = await client().POST(
      '/workOrders/{workOrderId}/close-request',
      {
        params: { path: { workOrderId } },
        // An undefined reason is dropped by JSON serialisation, so the service
        // receives {} and Odoo gets no reason.
        body: { reason },
      }
    )

    if (fetchResponse.response.ok) {
      return { ok: true, data: null }
    }

    // Odoo refused: a request is already pending, or the work order is closed
    // or hidden from Mina sidor. The tenant is told so. It is not a failure.
    if (fetchResponse.response.status === 409) {
      return { ok: false, err: 'conflict' }
    }

    logger.error(
      { status: fetchResponse.response.status, error: fetchResponse.error },
      'work-order-adapter.requestCloseWorkOrder'
    )
    return { ok: false, err: 'unknown' }
  } catch (error) {
    logger.error({ error }, 'work-order-adapter.requestCloseWorkOrder')
    return { ok: false, err: 'unknown' }
  }
}
```

- [ ] **Step 5: Run, expect PASS**, then commit

```sh
pnpm --filter @onecore/core exec jest src/adapters/tests/work-order-adapter.test.ts
pnpm --filter @onecore/core run typecheck
pnpm exec prettier --write core/src/adapters/work-order-adapter/index.ts core/src/adapters/tests/work-order-adapter.test.ts core/test/factories/work-order-external.ts
git add core/src/adapters/work-order-adapter core/src/adapters/tests/work-order-adapter.test.ts core/test/factories/work-order-external.ts
git commit -m "MIM-2036: add requestCloseWorkOrder to core's work-order adapter

Regenerate the work-order API types for the new close-request path
and WorkOrder.CloseRequestPending. The new adapter function sends an
optional reason and returns 'conflict' when the service answers 409.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task C5: Core `close-request` route, and `closeRequestPending` in core's Swagger

**Files:**
- Modify `core/src/services/work-order-service/schemas.ts` (line 26 in `CoreWorkOrderSchema`; re-export block lines 81-85)
- Modify `core/src/services/work-order-service/index.ts` (after lines 329, 437, 539, 640, 744 and 1433, each `status: v.Status,` in the six `CoreWorkOrder` mappings; insert a new route after line 2058, the end of the unchanged `/close` handler)
- Modify `core/test/factories/work-order.ts` (after line 28)
- Test `core/src/services/work-order-service/tests/index.test.ts` (insert after line 677; extend after line 162)
- Create/Test `core/src/services/work-order-service/tests/close-request.test.ts`

The staff route `POST /work-orders/:workOrderId/close` and its adapter call stay unchanged.

**Interfaces:**
- Consumes: `workOrderAdapter.requestCloseWorkOrder(workOrderId, reason?)` (C4); `CloseWorkOrderRequestSchema` from `@onecore/types` (C3); `OdooWorkOrder.CloseRequestPending` (regenerated in C4).
- Produces: `POST /work-orders/:workOrderId/close-request`, body `{ reason?: string }` → `200 { message }` / `400 { error: [...] }` / `409 { error: 'close-request-conflict' }` / `500 { message }`. This is what the .NET `OneCoreWorkOrderService` close now calls. Also `CoreWorkOrder.closeRequestPending: boolean` (JSON `closeRequestPending`).

- [ ] **Step 1: Write the failing tests**

In `core/src/services/work-order-service/tests/index.test.ts`, insert after line 677 (the closing `})` of the unchanged `describe('POST /work-orders/:workOrderId/close', ...)`):

```ts

  describe('POST /work-orders/:workOrderId/close-request', () => {
    it('forwards a close request without a reason', async () => {
      const requestCloseSpy = jest
        .spyOn(workOrderAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue({ ok: true, data: null })

      const res = await request(app.callback()).post(
        '/work-orders/13/close-request'
      )

      expect(res.status).toBe(200)
      expect(res.body.message).toBeDefined()
      expect(requestCloseSpy).toHaveBeenLastCalledWith('13', undefined)
    })

    it('forwards the reason the tenant gave', async () => {
      const requestCloseSpy = jest
        .spyOn(workOrderAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue({ ok: true, data: null })

      const res = await request(app.callback())
        .post('/work-orders/13/close-request')
        .send({ reason: 'Felet har försvunnit' })

      expect(res.status).toBe(200)
      expect(requestCloseSpy).toHaveBeenLastCalledWith(
        '13',
        'Felet har försvunnit'
      )
    })

    it('returns 409 when a close request is refused', async () => {
      jest
        .spyOn(workOrderAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue({ ok: false, err: 'conflict' })

      const res = await request(app.callback()).post(
        '/work-orders/13/close-request'
      )

      expect(res.status).toBe(409)
      expect(res.body.error).toBe('close-request-conflict')
    })

    it('returns 500 when the work-order service fails', async () => {
      jest
        .spyOn(workOrderAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue({ ok: false, err: 'unknown' })

      const res = await request(app.callback()).post(
        '/work-orders/13/close-request'
      )

      expect(res.status).toBe(500)
    })

    it('returns 400 and does not call the service when the reason is not a string', async () => {
      const requestCloseSpy = jest
        .spyOn(workOrderAdapter, 'requestCloseWorkOrder')
        .mockResolvedValue({ ok: true, data: null })
      requestCloseSpy.mockClear()

      const res = await request(app.callback())
        .post('/work-orders/13/close-request')
        .send({ reason: 42 })

      expect(res.status).toBe(400)
      expect(requestCloseSpy).not.toHaveBeenCalled()
    })
  })
```

In the same file, inside `describe('GET /work-orders/by-contact-code/:contactCode', ...)`, add after the first `it` (ending at line 162):

```ts

    // Mina sidor disables the close button on this flag, via the .NET API.
    it('should expose a pending close request as closeRequestPending', async () => {
      jest.spyOn(workOrderAdapter, 'getWorkOrdersByContactCode').mockResolvedValue({
        ok: true,
        data: [factory.externalOdooWorkOrder.build({ CloseRequestPending: true })],
      })

      const res = await request(app.callback()).get(
        '/work-orders/by-contact-code/P174958'
      )

      expect(res.status).toBe(200)
      expect(res.body.content.workOrders[0].closeRequestPending).toBe(true)
    })
```

Create `core/src/services/work-order-service/tests/close-request.test.ts`. The core route runs on top of the
real core adapter, and the work-order service is replaced by msw. Together
with C3's `close-request.test.ts` (Odoo fault → service 409), this covers the whole
chain up to the .NET API: Odoo fault → service 409 → core 409, and a non-conflict fault
→ service 500 → core 500.

```ts
import request from 'supertest'
import KoaRouter from '@koa/router'
import Koa from 'koa'
import bodyParser from 'koa-bodyparser'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

import config from '../../../common/config'
import { routes } from '../index'

// Stands in for the work-order service. The core route and adapter are the
// real ones, so this pins how the service's status reaches the .NET API.
const mockServer = setupServer()

const app = new Koa()
const router = new KoaRouter()
routes(router)
app.use(bodyParser())
app.use(router.routes())

describe('POST /work-orders/:workOrderId/close-request against the work-order service', () => {
  beforeAll(() => {
    // supertest's own requests to the in-process app must go through untouched
    mockServer.listen({ onUnhandledRequest: 'bypass' })
  })

  afterEach(() => {
    mockServer.resetHandlers()
  })

  afterAll(() => {
    mockServer.close()
  })

  it('answers 409, not 500, when the service reports a close-request conflict', async () => {
    mockServer.use(
      http.post(
        `${config.workOrderService.url}/workOrders/13/close-request`,
        () =>
          HttpResponse.json(
            { error: 'close-request-conflict', reason: 'already_pending' },
            { status: 409 }
          )
      )
    )

    const res = await request(app.callback()).post(
      '/work-orders/13/close-request'
    )

    expect(res.status).toBe(409)
    expect(res.body.error).toBe('close-request-conflict')
  })

  it('answers 500 when the service fails for any other reason', async () => {
    mockServer.use(
      http.post(
        `${config.workOrderService.url}/workOrders/13/close-request`,
        () =>
          HttpResponse.json(
            { error: 'XML-RPC fault: Traceback' },
            { status: 500 }
          )
      )
    )

    const res = await request(app.callback()).post(
      '/work-orders/13/close-request'
    )

    expect(res.status).toBe(500)
  })

  it('passes the reason through to the service, and nothing when it is omitted', async () => {
    const received: unknown[] = []
    mockServer.use(
      http.post(
        `${config.workOrderService.url}/workOrders/13/close-request`,
        async ({ request }) => {
          received.push(await request.json())
          return HttpResponse.json(
            { message: 'Close requested for work order with ID 13' },
            { status: 200 }
          )
        }
      )
    )

    const withReason = await request(app.callback())
      .post('/work-orders/13/close-request')
      .send({ reason: 'Det fungerar igen' })
    const withoutReason = await request(app.callback()).post(
      '/work-orders/13/close-request'
    )

    expect(withReason.status).toBe(200)
    expect(withoutReason.status).toBe(200)
    expect(received).toEqual([{ reason: 'Det fungerar igen' }, {}])
  })
})
```

- [ ] **Step 2: Run them, expect FAIL**

```sh
pnpm --filter @onecore/core exec jest src/services/work-order-service/tests/index.test.ts -t 'close-request|closeRequestPending'
pnpm --filter @onecore/core exec jest src/services/work-order-service/tests/close-request.test.ts
```

Expected: every `/close-request` case gets `404`, because the route does not exist yet.
`closeRequestPending` is `undefined`. The unchanged `/close` test still passes.

- [ ] **Step 3: Implement**

`core/src/services/work-order-service/schemas.ts`: in `CoreWorkOrderSchema`, after line 26 (`hiddenFromMyPages: z.boolean().optional(),`) insert:

```ts
  // True while the tenant's request to close the case awaits a decision in Odoo.
  closeRequestPending: z.boolean(),
```

In the `@onecore/types` re-export block (lines 81-85), add `CloseWorkOrderRequestSchema,` after `CreateInspectionWorkOrdersResponseSchema,`.

`core/src/services/work-order-service/index.ts`: insert the new route first, while line
numbers are still original. Put it after line 2058 (`  })`, the end of the unchanged
`/work-orders/:workOrderId/close` handler), before the `/work-orders/send-sms` JSDoc:

```ts

  /**
   * @swagger
   * /work-orders/{workOrderId}/close-request:
   *   post:
   *     summary: Request, on the tenant's behalf, that a work order be closed
   *     tags:
   *       - Work Order Service
   *     description: |
   *       Asks for the Odoo work order to be closed. The handler of the case
   *       decides in Odoo; nothing is closed here. Used by Mina sidor via the
   *       .NET API. Staff close with /work-orders/{workOrderId}/close.
   *     parameters:
   *       - in: path
   *         name: workOrderId
   *         required: true
   *         schema:
   *           type: string
   *         description: The Odoo id of the work order.
   *     requestBody:
   *       required: false
   *       content:
   *         application/json:
   *           schema:
   *             type: object
   *             properties:
   *               reason:
   *                 type: string
   *                 description: Optional reason from the tenant, shown to the handler.
   *     responses:
   *       '200':
   *         description: Close request recorded.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 message:
   *                   type: string
   *                   example: Close requested for work order with ID {workOrderId}
   *       '400':
   *         description: The request body is malformed.
   *       '409':
   *         description: Refused. A request is already pending, or the work order is closed or hidden from Mina sidor.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 error:
   *                   type: string
   *                   example: close-request-conflict
   *       '500':
   *         description: Internal server error. The work-order service or Odoo failed.
   *         content:
   *           application/json:
   *             schema:
   *               type: object
   *               properties:
   *                 message:
   *                   type: string
   *                   example: Failed to request close of work order with ID {workOrderId}
   *     security:
   *       - bearerAuth: []
   */
  router.post('/work-orders/:workOrderId/close-request', async (ctx) => {
    const metadata = generateRouteMetadata(ctx)
    const { workOrderId } = ctx.params

    // An empty POST has no body at all. That is a request without a reason.
    const body = schemas.CloseWorkOrderRequestSchema.safeParse(
      ctx.request.body ?? {}
    )
    if (!body.success) {
      ctx.status = 400
      ctx.body = {
        error: body.error.issues.map(({ message, path }) => ({ message, path })),
        ...metadata,
      }
      return
    }

    const result = await workOrderAdapter.requestCloseWorkOrder(
      workOrderId,
      body.data.reason
    )

    if (result.ok) {
      ctx.status = 200
      ctx.body = {
        message: `Close requested for work order with ID ${workOrderId}`,
        ...metadata,
      }
      return
    }

    if (result.err === 'conflict') {
      ctx.status = 409
      ctx.body = { error: 'close-request-conflict', ...metadata }
      return
    }

    ctx.status = 500
    ctx.body = {
      message: `Failed to request close of work order with ID ${workOrderId}`,
      ...metadata,
    }
  })
```

Then, in each of the six `CoreWorkOrder` mappings, insert
`closeRequestPending: v.CloseRequestPending,` on the line after `status: v.Status,`, at that
line's indentation. The original lines are 329 (by-contact-code), 437 (by-rental-property-id),
539 (by-property-id), 640 (by-building-id), 744 (by-maintenance-unit-code) and 1433 (by-code).
Work from the bottom up so the earlier numbers still hold. Do not touch the
`CoreXpandWorkOrder` mappings at 876, 986, 1097, 1204 and 1332. The field is required in
`CoreWorkOrderSchema`, so `tsc` flags any site you miss.

`core/test/factories/work-order.ts`: after line 28 (`dueDate: null,` in `WorkOrderFactory`) insert `    closeRequestPending: false,`.

- [ ] **Step 4: Run, expect PASS, and verify the whole monorepo**

```sh
pnpm --filter @onecore/core exec jest src/services/work-order-service src/adapters/tests/work-order-adapter.test.ts
pnpm --filter @onecore/work-order exec jest
pnpm run build:libs
pnpm run typecheck     # must be zero errors
pnpm run lint          # must be zero errors
```

- [ ] **Step 5: Commit**

```sh
pnpm exec prettier --write core/src/services/work-order-service/schemas.ts core/src/services/work-order-service/index.ts core/test/factories/work-order.ts core/src/services/work-order-service/tests/index.test.ts core/src/services/work-order-service/tests/close-request.test.ts
git add core
git commit -m "MIM-2036: add the tenant close-request route to core

POST /work-orders/:id/close-request forwards the optional reason and
answers with the service's outcome: 200, 409 when Odoo refuses the
request, 400 for a malformed body, or 500. Work orders now carry
closeRequestPending. The staff close route is unchanged.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task C6: Bring the workspace's MESSAGE_DOMAIN note up to date

**Files:**
- Modify `docs/end-to-end-flows.md (in the Mimer workspace root, the directory that holds the repos)` (lines 50 and 53-59). This is the workspace doc and is not in any git repo, so there is no commit step.

**Interfaces:** none (documentation).

- [ ] **Step 1: Replace the Types row (line 50)**

The row claims `libs/types/src/work-order/index.ts` holds the Zod contract. It holds
TypeScript interfaces that nothing imports. Replace line 50 with:

```md
| Types | `onecore/services/work-order/.../schemas.ts` → service Swagger → `core/src/adapters/work-order-adapter/generated/api-types.ts` | Zod contract for `WorkOrder` / `OdooWorkOrder` / `OdooWorkOrderMessage` lives in the service and reaches core only through regenerated types. Request bodies shared by both (e.g. `CloseWorkOrderRequestSchema`) live in `libs/types/src/work-order/schema.ts`. |
```

- [ ] **Step 2: Replace the trap paragraph (lines 53-59)**

```md
**The trap.** `MESSAGE_DOMAIN` currently whitelists exactly:
`from_tenant`, `close_request_from_tenant`, `close_request_declined`,
`receipt_to_tenant`, `tenant_sms`, `tenant_mail`, `tenant_mail_and_sms`,
`tenant_my_pages`, and the three `failed_*` variants. A message posted in Odoo
with any other `message_type` (including Odoo's default `comment`) is written
successfully, shows in the Odoo chatter, and is **silently invisible** on Mina
sidor. Every other layer reports success. If a task involves a new kind of
tenant-visible message, that array is the first thing to change. Also decide
whether the tenant or Mimer is its author. `messageAuthor` in `odoo-adapter/utils.ts`
treats only `from_tenant` and `close_request_from_tenant` as the tenant's own.
```

- [ ] **Step 3: Verify**

```sh
grep -n "close_request_from_tenant\|receipt_to_tenant\|tenant_my_pages" docs/end-to-end-flows.md (in the Mimer workspace root, the directory that holds the repos)
```

Expected: all three appear in the trap paragraph. Compare the list once more against
`MESSAGE_DOMAIN` in the merged `odoo-adapter/index.ts`.

---

## Notes and facts that differ from the spec

1. **`libs/types` has no work-order Zod schema** (as in contract REVISION 1).
   `libs/types/src/work-order/index.ts` has a plain TS `interface WorkOrder` that nothing
   imports. `CloseRequestPending` therefore goes into the service's `WorkOrderSchema`
   (C1) and reaches core through the regenerated `api-types.ts`. `libs/types` gets
   `CloseWorkOrderRequestSchema` (C3), which is truly shared by the service and core.
2. **Note, not a task: core's existing `closeWorkOrder` is broken already, and stays so.**
   `core/src/adapters/work-order-adapter/index.ts:556-579` reads `data.content.message`,
   but the service's `/close` returns `{ message, ...metadata }` with no `content`
   wrapper. So the adapter always returns `{ ok: false, err: 'unknown' }`. The core `/close`
   route answers 200 anyway, because it checks the always-truthy result object. property-tree's
   inspection close therefore works only by accident, and a real service failure is also
   reported as 200. Per REVISION 1 it is left unchanged. It is worth a follow-up ticket.
3. **The service 409 body carries `reason`, but core drops it.** The contract's core error
   type is `'conflict' | 'unknown'`, so the .NET API cannot tell `already_pending` from
   `closed` or `hidden`.
4. **Odoo must store no tenant-facing sender on `close_request_from_tenant`**, and must
   store one on `close_request_declined`. `messageAuthor` now ignores
   `onecore_tenant_author_name` for the former, like `from_tenant`. The declined message
   falls back to "Mimer" unless MIM-2040's Odoo-side sender logic also covers the new
   type. The Odoo section should confirm both.
5. The XML-RPC fault format was checked in `odoo/addons/rpc/controllers/xmlrpc.py`:
   `/xmlrpc/2` returns `Fault(2, str(UserError))`, and the `xmlrpc` npm client rejects with
   `Error('XML-RPC fault: ' + faultString)`. So "the message contains
   `close_request_conflict:`" holds for odoo-await, which uses `/xmlrpc/2/object`.
   It would not hold on the legacy `/xmlrpc/object` endpoint.

---

## mimer-nu/API (.NET 6) — tasks A1–A5

**Repo:** `mimer-nu/API`, branch `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism`, cut from
`epic/mim-1983-odoo-prioritized-ux-and-communication-improvements` (identical to `main` at `f011900` when this was written).

**No test project exists today.** The solution (`mimer-api.sln`) has WebApi, Core, Application, Infrastructure,
MessageQueueReceiver, Common, MessageHandler, Console and BackgroundJob — no `*Tests*.csproj`, and no xunit/nunit/Moq
reference anywhere. Task A1 adds the smallest one that works: `tests/Api.Tests` (xunit + Moq, net6.0), with
`InternalsVisibleTo` on Application and Infrastructure, because the handlers and `OneCoreWorkOrderService` are `internal`.

Everything below was checked in a scratch copy of the repo: `dotnet build mimer-api.sln` gives 0 errors, and
`dotnet test` passes 35/35 after A5. Each step's expected failure is the one that copy actually produced.

**Contract REVISION 1:** the tenant close request has its own core route. `OneCoreWorkOrderService.CloseWorkOrder` POSTs to core `work-orders/{id}/close-request`. Core's staff `work-orders/{id}/close` (used by property-tree) is not called from the API. The Mina sidor URL `~/api/workorders/close/{workOrderId}` is unchanged.

**Facts the tasks rely on (read from the code):**

- The tenant's contact code comes from `Core.Crossccutting.ICurrentUser.ContactCode` (`WebApi/Services/CurrentUser.cs`:
  the JWT `ClaimTypes.Name`, registered scoped in `Program.cs:66`). Other handlers already inject it this way, e.g.
  `DeleteNoteOfInterestCommandHandler`. The close and update routes carry no contact code, so `IPreAuthorizeRequest`
  cannot be used here.
- The tenant's Odoo work orders come from core's `GET /work-orders/by-contact-code/{contactCode}`, which
  `IOneCoreWorkOrderService.GetWorkOrdersByContactCode` already calls (used by `GetWorkOrderListQueryHandler`). That
  method turns any non-200 into an empty list, so a handler could not tell "core is down" (502) from "not yours" (403).
  A2 adds `TryGetWorkOrdersByContactCode`, which makes the same core call but returns `null` on failure. It is not a
  new core endpoint, and the existing method is left alone so the list and dashboard keep degrading as they do today.
- Odoo work orders have `Code = "od-" + odoo id` (`onecore/services/work-order/.../odoo-adapter/utils.ts:63`), and
  Mina sidor sends `workorderCode.replace('od-', '')` as `{workOrderId}` (`WorkorderList.vue:288,298`). So a work order
  counts as the tenant's own when `"od-" + workOrderId` is among their codes. Matching the whole code also stops an
  Xpand code that happens to be the same number from counting as owned.
- The existing result pattern in this area is the per-command response class (`CloseWorkOrderResponse` /
  `UpdateWorkOrderResponse` with `Success` + `Message`). A2 adds a `Status` enum to those classes. It does not
  introduce a new generic result type, and it does not throw exceptions: `ConflictException` only has an
  "Entity already exists" constructor, and there is no exception type that maps to 502.
- Feature flag: both handlers `throw new NotImplementedException` when `FeatureManagement:OneCoreWorkOrders != "true"`.
  `ProblemDetailsApplicationBuilderExtensions.DetermineStatusCode` has no case for it, so the client gets a 500. The
  tasks keep that as is, keep the check first (before auth and ownership, so no core call happens when the flag is
  off), and pin it with a test.
- Core's current close/update responses are `{ message, ...metadata }` with no `content` wrapper
  (`onecore/core/src/services/work-order-service/index.ts:1967-2060`). Today's code deserializes
  `OneCoreResponseWrapper<…>.Content`, which is `null`, and then reads `.Message` on the failure path. So a core
  failure currently throws `NullReferenceException` (500) instead of returning `false`. A2 stops parsing these bodies
  and uses only the status code.
- Serialization: API responses use System.Text.Json web defaults (`Program.cs:55`), so `CloseRequestPending` goes out
  as `closeRequestPending`. Inbound core JSON is parsed with Newtonsoft, which matches property names
  case-insensitively, so core's camelCase `closeRequestPending` lands in `WorkOrderResponse.CloseRequestPending` with
  no attribute. AutoMapper (`WorkOrderMappingProfile`) leaves the new property `false` for Xpand/DB work orders.
  `AssertConfigurationIsValid` is never called, so the unmapped member does not break anything.

---

### Task A1: Add a test project (xunit + Moq) to the solution

**Files:**
- Create: `tests/Api.Tests/Api.Tests.csproj`
- Create: `tests/Api.Tests/WorkOrders/CloseWorkOrderFeatureFlagTests.cs`
- Modify: `src/Application/Application.csproj` (insert before `</Project>`, line 44)
- Modify: `src/Infrastructure/Infrastructure.csproj` (insert before `</Project>`, line 46)
- Modify: `mimer-api.sln` (via `dotnet sln add`)

**Interfaces:**
- Consumes: existing `CloseWorkOrderCommandHandler(IConfiguration, ILogger<>, IOneCoreWorkOrderService)`
- Produces: test project `Api.Tests`, referencing Application, Infrastructure and WebApi, with access to their internals

- [ ] **Step 1: Write the failing test**

`tests/Api.Tests/Api.Tests.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">

	<PropertyGroup>
		<TargetFramework>net6.0</TargetFramework>
		<ImplicitUsings>enable</ImplicitUsings>
		<Nullable>enable</Nullable>
		<LangVersion>latest</LangVersion>
		<IsPackable>false</IsPackable>
	</PropertyGroup>

	<ItemGroup>
		<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.5.0" />
		<PackageReference Include="Moq" Version="4.18.4" />
		<PackageReference Include="xunit" Version="2.4.2" />
		<PackageReference Include="xunit.runner.visualstudio" Version="2.4.5">
			<PrivateAssets>all</PrivateAssets>
			<IncludeAssets>runtime; build; native; contentfiles; analyzers; buildtransitive</IncludeAssets>
		</PackageReference>
	</ItemGroup>

	<ItemGroup>
		<ProjectReference Include="..\..\src\Application\Application.csproj" />
		<ProjectReference Include="..\..\src\Infrastructure\Infrastructure.csproj" />
		<ProjectReference Include="..\..\src\WebApi\WebApi.csproj" />
	</ItemGroup>

</Project>
```

`tests/Api.Tests/WorkOrders/CloseWorkOrderFeatureFlagTests.cs` is a characterization test of the flag behaviour that
A3 and A4 must keep:

```csharp
using Application.Business.WorkOrder.Commands.CloseWorkOrder;
using Application.Common.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace Api.Tests.WorkOrders;

public class CloseWorkOrderFeatureFlagTests
{
    [Fact]
    public async Task Throws_NotImplemented_when_OneCoreWorkOrders_is_disabled()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["FeatureManagement:OneCoreWorkOrders"] = "false"
            })
            .Build();
        var oneCore = new Mock<IOneCoreWorkOrderService>(MockBehavior.Strict);

        var handler = new CloseWorkOrderCommandHandler(
            configuration,
            NullLogger<CloseWorkOrderCommandHandler>.Instance,
            oneCore.Object);

        await Assert.ThrowsAsync<NotImplementedException>(
            () => handler.Handle(new CloseWorkOrderCommand("42"), CancellationToken.None));
    }
}
```

Then add the project to the solution:

```sh
cd mimer-nu/API
dotnet sln mimer-api.sln add tests/Api.Tests/Api.Tests.csproj
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj
```

Expected: build error `CS0122: 'CloseWorkOrderCommandHandler' is inaccessible due to its protection level`. The
handler is `internal`.

- [ ] **Step 3: Implement**

Add this block to both `src/Application/Application.csproj` and `src/Infrastructure/Infrastructure.csproj`, just
before the closing `</Project>` (tab-indented like the rest of these files):

```xml
	<ItemGroup>
		<InternalsVisibleTo Include="Api.Tests" />
	</ItemGroup>
```

No `DynamicProxyGenAssembly2` entry is needed: Moq only proxies public interfaces (`IOneCoreWorkOrderService`,
`ICurrentUser`, `IMediator`), and the tests use `NullLogger<T>.Instance` for loggers of internal types.

- [ ] **Step 4: Run, expect PASS**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj     # Passed: 1
dotnet build mimer-api.sln                       # 0 Error(s)
```

CI impact: the Azure pipelines build `**/*.csproj` (`test-api-pipelines.yml:49,55`), so they will compile the test
project too. It restores from nuget.org, which the `feedsToUse: select` task includes by default. Publish uses
`publishWebProjects: true`, so the test project is not published. The Dockerfile restores and builds only
`src/WebApi/WebApi.csproj` and is unaffected. The pipelines do not run `dotnet test`. Adding a test step is a
separate decision, not part of this ticket.

- [ ] **Step 5: Commit**

```sh
git add tests/Api.Tests mimer-api.sln src/Application/Application.csproj src/Infrastructure/Infrastructure.csproj
git commit -m "Add xunit test project for Application and Infrastructure

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A2: Command status type and OneCoreWorkOrderService close/update/lookup

**Files:**
- Create: `src/Application/Business/WorkOrder/Commands/Shared/Models/WorkOrderCommandStatus.cs`
- Modify: `src/Application/Business/WorkOrder/Commands/Shared/Models/CloseWorkOrderResponse.cs` (whole file, 7 lines)
- Modify: `src/Application/Business/WorkOrder/Commands/Shared/Models/UpdateWorkOrderResponse.cs` (whole file, 7 lines)
- Modify: `src/Application/Business/WorkOrder/Commands/CloseWorkOrder/CloseWorkOrderCommand.cs` (whole file, 16 lines)
- Modify: `src/Application/Business/WorkOrder/Queries/GetWorkOrders/WorkOrderResponse.cs` (insert after line 21)
- Modify: `src/Application/Common/Infrastructure/IOneCoreWorkOrderService.cs` (lines 9-23)
- Modify: `src/Infrastructure/OneCore/OneCoreWorkOrderService.cs` (usings line 9, field after line 21, new method after line 54, replace lines 73-113)
- Modify: `src/Infrastructure/OneCore/Models/WorkOrder.cs` (append after line 17)
- Modify: `src/Application/Business/WorkOrder/Commands/CloseWorkOrder/CloseWorkOrderHandler.cs` (lines 37-52, keeps it compiling; rewritten in A3)
- Modify: `src/Application/Business/WorkOrder/Commands/UpdateWorkOrder/UpdateWorkOrderCommandHandler.cs` (lines 37-52, keeps it compiling; rewritten in A4)
- Create (test): `tests/Api.Tests/TestDoubles/FakeCoreHandler.cs`
- Create (test): `tests/Api.Tests/WorkOrders/OneCoreWorkOrderServiceTests.cs`

**Interfaces:**
- Consumes: core `POST /work-orders/{id}/close-request` (contract REVISION 1; the staff `/close` route is untouched) body `{}` or `{ "reason": string }` → 200 / 400 / 409 / 500 (400 and 500 both map to UpstreamFailed); core `POST /work-orders/{id}/update` body `{ message: string }` → 200 / 400 / 500; core `GET /work-orders/by-contact-code/{contactCode}` → `{ content: { totalCount, workOrders: [{ …, code, closeRequestPending }] } }`
- Produces:
  - `enum WorkOrderCommandStatus { Success, Forbidden, Conflict, UpstreamFailed }`
  - `CloseWorkOrderResponse.Status` / `UpdateWorkOrderResponse.Status`
  - `CloseWorkOrderCommand(string workOrderId, string? reason = null)` with `string? Reason`
  - `WorkOrderResponse.CloseRequestPending` (bool)
  - `IOneCoreWorkOrderService.TryGetWorkOrdersByContactCode(string) : Task<WorkOrdersResponse?>`
  - `IOneCoreWorkOrderService.CloseWorkOrder(CloseWorkOrderCommand) : Task<WorkOrderCommandStatus>`
  - `IOneCoreWorkOrderService.UpdateWorkOrder(UpdateWorkOrderCommand) : Task<WorkOrderCommandStatus>`

- [ ] **Step 1: Write the failing test**

`tests/Api.Tests/TestDoubles/FakeCoreHandler.cs`:

```csharp
using System.Net;
using System.Text;

namespace Api.Tests.TestDoubles;

/// <summary>
/// Stands in for ONECore core: answers /auth/generatetoken with a token and
/// every other request with the configured status and body, recording what it received.
/// </summary>
internal class FakeCoreHandler : HttpMessageHandler
{
    private readonly HttpStatusCode _status;
    private readonly string _body;
    private readonly Exception? _throwOnCall;

    public FakeCoreHandler(HttpStatusCode status, string body = "{}", Exception? throwOnCall = null)
    {
        _status = status;
        _body = body;
        _throwOnCall = throwOnCall;
    }

    public List<(HttpMethod Method, string Path, string? Body)> Calls { get; } = new();

    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var path = request.RequestUri!.AbsolutePath;

        if (path == "/auth/generatetoken")
        {
            return Json(HttpStatusCode.OK, "{\"token\":\"test-token\"}");
        }

        var body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
        Calls.Add((request.Method, path, body));

        if (_throwOnCall is not null)
        {
            throw _throwOnCall;
        }

        return Json(_status, _body);
    }

    private static HttpResponseMessage Json(HttpStatusCode status, string body) =>
        new(status) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
}
```

`tests/Api.Tests/WorkOrders/OneCoreWorkOrderServiceTests.cs`:

```csharp
using System.Net;
using System.Text.Json;
using Api.Tests.TestDoubles;
using Application.Business.WorkOrder.Commands.CloseWorkOrder;
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Business.WorkOrder.Commands.UpdateWorkOrder;
using Infrastructure.OneCore;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Api.Tests.WorkOrders;

public class OneCoreWorkOrderServiceTests
{
    private static OneCoreWorkOrderService CreateService(FakeCoreHandler handler) =>
        new(
            new OneCoreConfiguration { CoreURL = "http://core.test", CoreUsername = "user", CorePassword = "pass" },
            new HttpClient(handler),
            NullLogger<OneCoreWorkOrderService>.Instance);

    [Fact]
    public async Task CloseWorkOrder_posts_reason_as_json_and_returns_Success_on_200()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.OK, "{\"message\":\"ok\"}");
        var reason = "Det är \"fixat\"\nTack!";

        var status = await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", reason));

        Assert.Equal(WorkOrderCommandStatus.Success, status);
        var call = Assert.Single(handler.Calls);
        Assert.Equal(HttpMethod.Post, call.Method);
        Assert.Equal("/work-orders/42/close-request", call.Path);
        using var json = JsonDocument.Parse(call.Body!);
        Assert.Equal(reason, json.RootElement.GetProperty("reason").GetString());
    }

    [Fact]
    public async Task CloseWorkOrder_without_reason_sends_empty_object()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.OK);

        await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", null));

        var call = Assert.Single(handler.Calls);
        Assert.Equal("/work-orders/42/close-request", call.Path);
        Assert.Equal("{}", call.Body);
    }

    [Fact]
    public async Task CloseWorkOrder_maps_core_409_to_Conflict()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.Conflict, "{\"reason\":\"already_pending\"}");

        var status = await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", null));

        Assert.Equal(WorkOrderCommandStatus.Conflict, status);
    }

    [Fact]
    public async Task CloseWorkOrder_maps_core_400_to_UpstreamFailed()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.BadRequest, "{\"reason\":\"invalid body\"}");

        var status = await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", null));

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, status);
        Assert.Equal("/work-orders/42/close-request", Assert.Single(handler.Calls).Path);
    }

    [Fact]
    public async Task CloseWorkOrder_maps_core_500_to_UpstreamFailed()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.InternalServerError, "{\"message\":\"boom\"}");

        var status = await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", null));

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, status);
    }

    [Fact]
    public async Task CloseWorkOrder_maps_transport_error_to_UpstreamFailed()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.OK, throwOnCall: new HttpRequestException("connection refused"));

        var status = await CreateService(handler).CloseWorkOrder(new CloseWorkOrderCommand("42", null));

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, status);
    }

    [Fact]
    public async Task UpdateWorkOrder_posts_raw_message_as_json()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.OK, "{\"message\":\"ok\"}");
        var message = "Hej \"Mimer\"\nrad två\\slut";

        var status = await CreateService(handler).UpdateWorkOrder(new UpdateWorkOrderCommand("42", message));

        Assert.Equal(WorkOrderCommandStatus.Success, status);
        var call = Assert.Single(handler.Calls);
        Assert.Equal("/work-orders/42/update", call.Path);
        using var json = JsonDocument.Parse(call.Body!);
        Assert.Equal(message, json.RootElement.GetProperty("message").GetString());
    }

    [Fact]
    public async Task UpdateWorkOrder_maps_core_500_to_UpstreamFailed()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.InternalServerError, "{\"message\":\"boom\"}");

        var status = await CreateService(handler).UpdateWorkOrder(new UpdateWorkOrderCommand("42", "hej"));

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, status);
    }

    [Fact]
    public async Task TryGetWorkOrdersByContactCode_returns_work_orders_with_CloseRequestPending()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.OK,
            "{\"content\":{\"totalCount\":1,\"workOrders\":[{\"id\":\"6f9619ff-8b86-d011-b42d-00cf4fc964ff\",\"code\":\"od-42\",\"contactCode\":\"P123\",\"status\":\"Påbörjad\",\"registered\":\"2026-09-01T08:00:00Z\",\"hiddenFromMyPages\":false,\"closeRequestPending\":true,\"workOrderRows\":[],\"messages\":[]}]}}");

        var result = await CreateService(handler).TryGetWorkOrdersByContactCode("P123");

        Assert.NotNull(result);
        var workOrder = Assert.Single(result!.WorkOrders);
        Assert.Equal("od-42", workOrder.Code);
        Assert.True(workOrder.CloseRequestPending);
        Assert.Equal("/work-orders/by-contact-code/P123", Assert.Single(handler.Calls).Path);
    }

    [Fact]
    public async Task TryGetWorkOrdersByContactCode_returns_null_when_core_fails()
    {
        var handler = new FakeCoreHandler(HttpStatusCode.InternalServerError, "{\"message\":\"boom\"}");

        var result = await CreateService(handler).TryGetWorkOrdersByContactCode("P123");

        Assert.Null(result);
    }
}
```

The escaping tests parse the body with `JsonDocument` and compare the round-tripped value. They do not compare raw
strings: System.Text.Json's default encoder writes `"` as `"` and `å` as `å`, which is valid JSON and parses
back exactly.

- [ ] **Step 2: Run it, expect FAIL**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj
```

Expected build errors:
`CS0103: The name 'WorkOrderCommandStatus' does not exist in the current context`,
`CS1061: 'OneCoreWorkOrderService' does not contain a definition for 'TryGetWorkOrdersByContactCode'`,
`CS1729: 'CloseWorkOrderCommand' does not contain a constructor that takes 2 arguments`.

- [ ] **Step 3: Implement**

`src/Application/Business/WorkOrder/Commands/Shared/Models/WorkOrderCommandStatus.cs` (new):

```csharp
namespace Application.Business.WorkOrder.Commands.Shared.Models;

/// <summary>
/// Outcome of a tenant command (close request, message) on a ONECore work order.
/// The WorkOrdersController maps it to 204 / 403 / 409 / 502.
/// </summary>
public enum WorkOrderCommandStatus
{
    Success,
    Forbidden,
    Conflict,
    UpstreamFailed
}
```

`CloseWorkOrderResponse.cs` (replace whole file):

```csharp
namespace Application.Business.WorkOrder.Commands.Shared.Models;

public class CloseWorkOrderResponse
{
    public string Message { get; set; } = string.Empty;
    public bool Success { get; set; }
    public WorkOrderCommandStatus Status { get; set; }
}
```

`UpdateWorkOrderResponse.cs` (replace whole file):

```csharp
namespace Application.Business.WorkOrder.Commands.Shared.Models;

public class UpdateWorkOrderResponse
{
    public string Message { get; set; } = string.Empty;
    public bool Success { get; set; }
    public WorkOrderCommandStatus Status { get; set; }
}
```

`CloseWorkOrderCommand.cs` (replace whole file):

```csharp
using Application.Business.WorkOrder.Commands.Shared.Models;
using MediatR;

namespace Application.Business.WorkOrder.Commands.CloseWorkOrder;

public class CloseWorkOrderCommand : IRequest<CloseWorkOrderResponse>
{
    public CloseWorkOrderCommand(
        string workOrderId,
        string? reason = null
    )
    {
        WorkOrderId = workOrderId;
        Reason = reason;
    }

    public string WorkOrderId { get; set; }

    public string? Reason { get; set; }
}
```

`WorkOrderResponse.cs`: insert after line 21 (`public bool HiddenFromMyPages { get; set; } = false;`):

```csharp
    public bool CloseRequestPending { get; set; }
```

`IOneCoreWorkOrderService.cs`: add `using Application.Business.WorkOrder.Commands.Shared.Models;` after line 9, and
replace the interface body (lines 13-24) with:

```csharp
public interface IOneCoreWorkOrderService
{
  Task<WorkOrdersResponse> GetWorkOrdersByContactCode(string contactCode);

  /// <summary>
  /// Same core call as <see cref="GetWorkOrdersByContactCode"/>, but returns null when
  /// core cannot be reached or answers with a non-200, so callers can tell
  /// "no work orders" apart from "core is down".
  /// </summary>
  Task<WorkOrdersResponse?> TryGetWorkOrdersByContactCode(string contactCode);

  Task<bool> CreateWorkOrder(CreateWorkOrderCommand request);

  Task<WorkOrderCommandStatus> CloseWorkOrder(CloseWorkOrderCommand request);

  Task<List<MaintenanceUnitResponse>> GetMaintenanceUnitsByContactCode(string contactCode);
  
  Task<WorkOrderCommandStatus> UpdateWorkOrder(UpdateWorkOrderCommand request);
}
```

`src/Infrastructure/OneCore/Models/WorkOrder.cs`: append after line 17:

```csharp

internal class CloseWorkOrderRequestBody
{
    [System.Text.Json.Serialization.JsonPropertyName("reason")]
    public string? Reason { get; set; }
}

internal class UpdateWorkOrderRequestBody
{
    [System.Text.Json.Serialization.JsonPropertyName("message")]
    public string Message { get; set; } = string.Empty;
}
```

`src/Infrastructure/OneCore/OneCoreWorkOrderService.cs`:

1. After line 9 (`using Application.Business.WorkOrder.Commands.UpdateWorkOrder;`) add
   `using Application.Business.WorkOrder.Commands.Shared.Models;`
2. After line 21 (`private readonly HttpClient _httpClient;`) add a blank line and:

```csharp
  private static readonly System.Text.Json.JsonSerializerOptions RequestBodyJsonOptions = new()
  {
    DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
  };
```

`WhenWritingNull` matters: without it, a missing reason goes out as `{"reason":null}`. The onecore route declares
`reason?: string`, and a Zod `z.string().optional()` rejects `null`.

3. After the end of `GetWorkOrdersByContactCode` (line 54), insert:

```csharp

  public async Task<WorkOrdersResponse?> TryGetWorkOrdersByContactCode(string contactCode)
  {
    try
    {
      var token = await AuthorizeHelper.AuthorizeApplicationAsync(_oneCoreConfiguration, _httpClient);
      _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
      var response = await _httpClient.GetAsync(_oneCoreConfiguration.CoreURL + "/work-orders/by-contact-code/" + Uri.EscapeDataString(contactCode));
      var json = await response.Content.ReadAsStringAsync();

      if (response.StatusCode != HttpStatusCode.OK)
      {
        _logger.LogWarning("Failed to get work orders from Core: {StatusCode} {Body}", response.StatusCode, json);
        return null;
      }

      return JsonConvert.DeserializeObject<OneCoreResponseWrapper<WorkOrdersResponse>>(json)?.Content;
    }
    catch (Exception ex)
    {
      _logger.LogError(ex, "Failed to get work orders from Core for {ContactCode}", contactCode);
      return null;
    }
  }
```

4. Replace `CloseWorkOrder` and `UpdateWorkOrder` (original lines 73-113, from `public async Task<bool> CloseWorkOrder`
   up to the blank line before `GetMaintenanceUnitsByContactCode`) with:

```csharp
  public async Task<WorkOrderCommandStatus> CloseWorkOrder(CloseWorkOrderCommand request)
  {
    var body = new CloseWorkOrderRequestBody { Reason = request.Reason };
    return await PostWorkOrderCommand(request.WorkOrderId, "close-request", body);
  }

  public async Task<WorkOrderCommandStatus> UpdateWorkOrder(UpdateWorkOrderCommand request)
  {
    var body = new UpdateWorkOrderRequestBody { Message = request.Message };
    return await PostWorkOrderCommand(request.WorkOrderId, "update", body);
  }

  private async Task<WorkOrderCommandStatus> PostWorkOrderCommand<TBody>(string workOrderId, string action, TBody body)
  {
    try
    {
      var token = await AuthorizeHelper.AuthorizeApplicationAsync(_oneCoreConfiguration, _httpClient);
      _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

      var json = System.Text.Json.JsonSerializer.Serialize(body, RequestBodyJsonOptions);
      var content = new StringContent(json, System.Text.Encoding.UTF8, "application/json");
      var response = await _httpClient.PostAsync(
          new Uri(_oneCoreConfiguration.CoreURL + "/work-orders/" + Uri.EscapeDataString(workOrderId) + "/" + action), content);

      if (response.IsSuccessStatusCode)
      {
        return WorkOrderCommandStatus.Success;
      }

      var responseBody = await response.Content.ReadAsStringAsync();

      if (response.StatusCode == HttpStatusCode.Conflict)
      {
        _logger.LogInformation("Core refused to {Action} work order {WorkOrderId}: {Body}", action, workOrderId, responseBody);
        return WorkOrderCommandStatus.Conflict;
      }

      _logger.LogError("Failed to {Action} work order {WorkOrderId}: {StatusCode} {Body}", action, workOrderId, response.StatusCode, responseBody);
      return WorkOrderCommandStatus.UpstreamFailed;
    }
    catch (Exception ex)
    {
      _logger.LogError(ex, "Failed to {Action} work order {WorkOrderId}", action, workOrderId);
      return WorkOrderCommandStatus.UpstreamFailed;
    }
  }

```

The response body is logged, never deserialized. That removes the `NullReferenceException` on the failure path
described above.

5. Keep both handlers compiling (A3 and A4 rewrite them). In `CloseWorkOrderHandler.cs`, add
   `using Application.Business.WorkOrder.Commands.Shared.Models;` if it is missing (it is already on line 1), and
   replace lines 37-52 (from `var success = await _oneCoreService.CloseWorkOrder(request);` to the last `};`) with:

```csharp
        var status = await _oneCoreService.CloseWorkOrder(request);

        return new CloseWorkOrderResponse
        {
            Message = status == WorkOrderCommandStatus.Success ? "Work order updated" : "Failed to update work order",
            Success = status == WorkOrderCommandStatus.Success,
            Status = status
        };
```

   Make the same change in `UpdateWorkOrderCommandHandler.cs` lines 37-52, with `UpdateWorkOrder` /
   `UpdateWorkOrderResponse`.

- [ ] **Step 4: Run, expect PASS**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj     # Passed: 11
dotnet build mimer-api.sln                       # 0 Error(s)
```

- [ ] **Step 5: Commit**

```sh
git add -A src tests
git commit -m "Return typed status from OneCore work order close/update and serialize bodies as JSON

Close and update now build their request bodies with System.Text.Json instead of
string concatenation, map core 409 to Conflict and any other failure to
UpstreamFailed, and no longer dereference a missing content wrapper on error.
Adds TryGetWorkOrdersByContactCode (null on core failure) and
WorkOrderResponse.CloseRequestPending.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A3: Ownership check, reason and validation in CloseWorkOrderCommandHandler

**Files:**
- Modify: `src/Application/Business/WorkOrder/Commands/CloseWorkOrder/CloseWorkOrderHandler.cs` (replace whole file)
- Create: `src/Application/Business/WorkOrder/Commands/CloseWorkOrder/CloseWorkOrderCommandValidator.cs`
- Delete (test): `tests/Api.Tests/WorkOrders/CloseWorkOrderFeatureFlagTests.cs` (the constructor changes; the flag case moves into the new file)
- Create (test): `tests/Api.Tests/TestDoubles/WorkOrderTestData.cs`
- Create (test): `tests/Api.Tests/WorkOrders/CloseWorkOrderCommandHandlerTests.cs`

**Interfaces:**
- Consumes: `ICurrentUser.ContactCode` / `IsAuthenticated`, `IOneCoreWorkOrderService.TryGetWorkOrdersByContactCode`, `IOneCoreWorkOrderService.CloseWorkOrder` (A2)
- Produces: `CloseWorkOrderCommandHandler(IConfiguration, ILogger<>, IOneCoreWorkOrderService, ICurrentUser)` returning `CloseWorkOrderResponse.Status` ∈ {Success, Forbidden, Conflict, UpstreamFailed}; throws `NotImplementedException` (flag off) and `UnauthorizedException` (no user); `CloseWorkOrderCommandValidator` (Reason ≤ 500 characters → otherwise `ValidationException` → 400 through `ValidationBehaviour`)

- [ ] **Step 1: Write the failing test**

`tests/Api.Tests/TestDoubles/WorkOrderTestData.cs`:

```csharp
using Application.Business.WorkOrder.Queries.GetWorkOrders;
using Core.Crossccutting;
using Microsoft.Extensions.Configuration;
using Moq;

namespace Api.Tests.TestDoubles;

internal static class WorkOrderTestData
{
    public const string TenantContactCode = "P123456";

    public static IConfiguration Configuration(bool oneCoreWorkOrdersEnabled = true) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["FeatureManagement:OneCoreWorkOrders"] = oneCoreWorkOrdersEnabled ? "true" : "false"
            })
            .Build();

    public static ICurrentUser Tenant(bool authenticated = true)
    {
        var user = new Mock<ICurrentUser>();
        user.SetupGet(x => x.IsAuthenticated).Returns(authenticated);
        user.SetupGet(x => x.ContactCode).Returns(authenticated ? TenantContactCode : string.Empty);
        user.SetupGet(x => x.UserName).Returns(authenticated ? TenantContactCode : string.Empty);
        return user.Object;
    }

    public static WorkOrdersResponse TenantWorkOrders(params string[] codes) =>
        new()
        {
            WorkOrders = codes.Select(code => new WorkOrderResponse { Code = code, ContactCode = TenantContactCode }).ToList(),
            TotalCount = codes.Length
        };
}
```

`tests/Api.Tests/WorkOrders/CloseWorkOrderCommandHandlerTests.cs`:

```csharp
using Api.Tests.TestDoubles;
using Application.Business.WorkOrder.Commands.CloseWorkOrder;
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Common.Exceptions;
using Application.Common.Infrastructure;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace Api.Tests.WorkOrders;

public class CloseWorkOrderCommandHandlerTests
{
    private readonly Mock<IOneCoreWorkOrderService> _oneCore = new();

    private CloseWorkOrderCommandHandler CreateHandler(bool enabled = true, bool authenticated = true) =>
        new(
            WorkOrderTestData.Configuration(enabled),
            NullLogger<CloseWorkOrderCommandHandler>.Instance,
            _oneCore.Object,
            WorkOrderTestData.Tenant(authenticated));

    private void TenantOwns(params string[] codes) =>
        _oneCore.Setup(x => x.TryGetWorkOrdersByContactCode(WorkOrderTestData.TenantContactCode))
            .ReturnsAsync(WorkOrderTestData.TenantWorkOrders(codes));

    [Fact]
    public async Task Throws_NotImplemented_when_OneCoreWorkOrders_is_disabled()
    {
        await Assert.ThrowsAsync<NotImplementedException>(
            () => CreateHandler(enabled: false).Handle(new CloseWorkOrderCommand("42"), CancellationToken.None));

        _oneCore.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task Throws_Unauthorized_when_no_tenant_is_logged_in()
    {
        await Assert.ThrowsAsync<UnauthorizedException>(
            () => CreateHandler(authenticated: false).Handle(new CloseWorkOrderCommand("42"), CancellationToken.None));

        _oneCore.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task Foreign_work_order_is_Forbidden_and_core_close_is_not_called()
    {
        TenantOwns("od-7", "od-8");

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42", "Klart"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Forbidden, response.Status);
        Assert.False(response.Success);
        _oneCore.Verify(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()), Times.Never);
    }

    [Fact]
    public async Task Xpand_work_order_code_with_same_number_is_not_treated_as_owned()
    {
        TenantOwns("42");

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Forbidden, response.Status);
        _oneCore.Verify(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()), Times.Never);
    }

    [Fact]
    public async Task Ownership_lookup_failure_is_UpstreamFailed_and_core_close_is_not_called()
    {
        _oneCore.Setup(x => x.TryGetWorkOrdersByContactCode(WorkOrderTestData.TenantContactCode))
            .ReturnsAsync((Application.Business.WorkOrder.Queries.GetWorkOrders.WorkOrdersResponse?)null);

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, response.Status);
        _oneCore.Verify(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()), Times.Never);
    }

    [Fact]
    public async Task Owned_work_order_is_closed_with_reason()
    {
        TenantOwns("od-42");
        _oneCore.Setup(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()))
            .ReturnsAsync(WorkOrderCommandStatus.Success);

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42", "Det är lagat"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Success, response.Status);
        Assert.True(response.Success);
        _oneCore.Verify(x => x.CloseWorkOrder(It.Is<CloseWorkOrderCommand>(c => c.WorkOrderId == "42" && c.Reason == "Det är lagat")), Times.Once);
    }

    [Fact]
    public async Task Core_conflict_is_passed_through()
    {
        TenantOwns("od-42");
        _oneCore.Setup(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()))
            .ReturnsAsync(WorkOrderCommandStatus.Conflict);

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Conflict, response.Status);
        Assert.False(response.Success);
    }

    [Fact]
    public async Task Core_failure_is_UpstreamFailed()
    {
        TenantOwns("od-42");
        _oneCore.Setup(x => x.CloseWorkOrder(It.IsAny<CloseWorkOrderCommand>()))
            .ReturnsAsync(WorkOrderCommandStatus.UpstreamFailed);

        var response = await CreateHandler().Handle(new CloseWorkOrderCommand("42"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, response.Status);
        Assert.False(response.Success);
    }

    [Fact]
    public void Validator_rejects_reason_longer_than_500_characters()
    {
        var validator = new CloseWorkOrderCommandValidator();

        Assert.False(validator.Validate(new CloseWorkOrderCommand("42", new string('a', 501))).IsValid);
        Assert.True(validator.Validate(new CloseWorkOrderCommand("42", new string('a', 500))).IsValid);
        Assert.True(validator.Validate(new CloseWorkOrderCommand("42")).IsValid);
        Assert.False(validator.Validate(new CloseWorkOrderCommand("")).IsValid);
    }
}
```

```sh
git rm tests/Api.Tests/WorkOrders/CloseWorkOrderFeatureFlagTests.cs
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj
```

Expected: `CS1729: 'CloseWorkOrderCommandHandler' does not contain a constructor that takes 4 arguments` and
`CS0246: The type or namespace name 'CloseWorkOrderCommandValidator' could not be found`.

- [ ] **Step 3: Implement**

`CloseWorkOrderHandler.cs` (replace whole file; the class name stays `CloseWorkOrderCommandHandler`):

```csharp
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Common.Exceptions;
using Application.Common.Infrastructure;
using Core.Crossccutting;
using MediatR;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Configuration;

namespace Application.Business.WorkOrder.Commands.CloseWorkOrder;

internal class CloseWorkOrderCommandHandler : IRequestHandler<CloseWorkOrderCommand, CloseWorkOrderResponse>
{
    private const string OneCoreWorkOrderCodePrefix = "od-";

    private readonly IConfiguration _configuration;
    private readonly ILogger<CloseWorkOrderCommandHandler> _logger;
    private readonly IOneCoreWorkOrderService _oneCoreService;
    private readonly ICurrentUser _currentUser;

    public CloseWorkOrderCommandHandler(
        IConfiguration configuration,
        ILogger<CloseWorkOrderCommandHandler> logger,
        IOneCoreWorkOrderService oneCoreService,
        ICurrentUser currentUser)
    {
        _configuration = configuration;
        _logger = logger;
        _oneCoreService = oneCoreService;
        _currentUser = currentUser;
    }

    public async Task<CloseWorkOrderResponse> Handle(CloseWorkOrderCommand request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        var isOneCoreWorkOrdersEnabled = _configuration["FeatureManagement:OneCoreWorkOrders"];

        if (isOneCoreWorkOrdersEnabled.ToLower() != "true")
        {
            throw new NotImplementedException("OneCoreWorkOrders are not enabled");
        }

        if (!_currentUser.IsAuthenticated || string.IsNullOrEmpty(_currentUser.ContactCode))
        {
            throw new UnauthorizedException("User is unauthorized");
        }

        var tenantWorkOrders = await _oneCoreService.TryGetWorkOrdersByContactCode(_currentUser.ContactCode);

        if (tenantWorkOrders is null)
        {
            return Result(WorkOrderCommandStatus.UpstreamFailed, "Could not verify work order ownership");
        }

        var workOrderCode = OneCoreWorkOrderCodePrefix + request.WorkOrderId;
        var isOwnWorkOrder = tenantWorkOrders.WorkOrders
            .Any(x => string.Equals(x.Code, workOrderCode, StringComparison.OrdinalIgnoreCase));

        if (!isOwnWorkOrder)
        {
            _logger.LogWarning("User {ContactCode} tried to request close of work order {WorkOrderId} they do not own",
                _currentUser.ContactCode, request.WorkOrderId);
            return Result(WorkOrderCommandStatus.Forbidden, "You do not have access to the resource");
        }

        var status = await _oneCoreService.CloseWorkOrder(request);

        return status switch
        {
            WorkOrderCommandStatus.Success => Result(status, "Close request sent"),
            WorkOrderCommandStatus.Conflict => Result(status, "A close request is already pending, or the work order can no longer be closed"),
            _ => Result(status, "Failed to request close of work order")
        };
    }

    private static CloseWorkOrderResponse Result(WorkOrderCommandStatus status, string message) =>
        new()
        {
            Status = status,
            Success = status == WorkOrderCommandStatus.Success,
            Message = message
        };
}
```

`CloseWorkOrderCommandValidator.cs` (new; `services.AddValidatorsFromAssembly` in `Application/DependencyInjection.cs:26`
picks it up):

```csharp
using FluentValidation;

namespace Application.Business.WorkOrder.Commands.CloseWorkOrder;

public class CloseWorkOrderCommandValidator : AbstractValidator<CloseWorkOrderCommand>
{
    public CloseWorkOrderCommandValidator()
    {
        RuleFor(x => x.WorkOrderId).NotEmpty();
        RuleFor(x => x.Reason).MaximumLength(500);
    }
}
```

Design notes:
- The flag check stays first and unchanged, so a disabled flag still gives `NotImplementedException` (500) and makes
  no core call.
- The ownership lookup does **not** filter `HiddenFromMyPages`. A hidden work order owned by the tenant reaches Odoo,
  which refuses it with `close_request_conflict:hidden`, so the answer is 409 as the spec's error table says, not 403.
- A failed ownership lookup returns `UpstreamFailed` (502), not `Forbidden`, as the spec's "Odoo/core down → 502" row requires.
- The README says to keep each use case vertical even if that duplicates code, so the few ownership lines are
  repeated in A4 rather than pulled into a shared helper.

- [ ] **Step 4: Run, expect PASS**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj     # Passed: 19
dotnet build mimer-api.sln                       # 0 Error(s)
```

- [ ] **Step 5: Commit**

```sh
git add -A src tests
git commit -m "Only let tenants request close of their own work orders

CloseWorkOrderCommandHandler now looks up the logged-in tenant's ONECore work
orders by the contact code from the token and returns Forbidden, without calling
core, when the id is not among them. Passes the optional reason through
(max 500 characters) and surfaces core conflicts and failures.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A4: Ownership check and error propagation in UpdateWorkOrderCommandHandler

**Files:**
- Modify: `src/Application/Business/WorkOrder/Commands/UpdateWorkOrder/UpdateWorkOrderCommandHandler.cs` (replace whole file)
- Create (test): `tests/Api.Tests/WorkOrders/UpdateWorkOrderCommandHandlerTests.cs`

**Interfaces:**
- Consumes: as A3, plus `IOneCoreWorkOrderService.UpdateWorkOrder` (A2)
- Produces: `UpdateWorkOrderCommandHandler(IConfiguration, ILogger<>, IOneCoreWorkOrderService, ICurrentUser)` returning `UpdateWorkOrderResponse.Status` ∈ {Success, Forbidden, UpstreamFailed} (Conflict only if core ever sends 409 on update; the controller maps it to 502)

- [ ] **Step 1: Write the failing test**

`tests/Api.Tests/WorkOrders/UpdateWorkOrderCommandHandlerTests.cs`:

```csharp
using Api.Tests.TestDoubles;
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Business.WorkOrder.Commands.UpdateWorkOrder;
using Application.Business.WorkOrder.Queries.GetWorkOrders;
using Application.Common.Exceptions;
using Application.Common.Infrastructure;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using Xunit;

namespace Api.Tests.WorkOrders;

public class UpdateWorkOrderCommandHandlerTests
{
    private readonly Mock<IOneCoreWorkOrderService> _oneCore = new();

    private UpdateWorkOrderCommandHandler CreateHandler(bool enabled = true, bool authenticated = true) =>
        new(
            WorkOrderTestData.Configuration(enabled),
            NullLogger<UpdateWorkOrderCommandHandler>.Instance,
            _oneCore.Object,
            WorkOrderTestData.Tenant(authenticated));

    private void TenantOwns(params string[] codes) =>
        _oneCore.Setup(x => x.TryGetWorkOrdersByContactCode(WorkOrderTestData.TenantContactCode))
            .ReturnsAsync(WorkOrderTestData.TenantWorkOrders(codes));

    [Fact]
    public async Task Throws_NotImplemented_when_OneCoreWorkOrders_is_disabled()
    {
        await Assert.ThrowsAsync<NotImplementedException>(
            () => CreateHandler(enabled: false).Handle(new UpdateWorkOrderCommand("42", "Hej"), CancellationToken.None));

        _oneCore.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task Throws_Unauthorized_when_no_tenant_is_logged_in()
    {
        await Assert.ThrowsAsync<UnauthorizedException>(
            () => CreateHandler(authenticated: false).Handle(new UpdateWorkOrderCommand("42", "Hej"), CancellationToken.None));

        _oneCore.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task Foreign_work_order_is_Forbidden_and_core_update_is_not_called()
    {
        TenantOwns("od-7");

        var response = await CreateHandler().Handle(new UpdateWorkOrderCommand("42", "Hej"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Forbidden, response.Status);
        Assert.False(response.Success);
        _oneCore.Verify(x => x.UpdateWorkOrder(It.IsAny<UpdateWorkOrderCommand>()), Times.Never);
    }

    [Fact]
    public async Task Ownership_lookup_failure_is_UpstreamFailed_and_core_update_is_not_called()
    {
        _oneCore.Setup(x => x.TryGetWorkOrdersByContactCode(WorkOrderTestData.TenantContactCode))
            .ReturnsAsync((WorkOrdersResponse?)null);

        var response = await CreateHandler().Handle(new UpdateWorkOrderCommand("42", "Hej"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, response.Status);
        _oneCore.Verify(x => x.UpdateWorkOrder(It.IsAny<UpdateWorkOrderCommand>()), Times.Never);
    }

    [Fact]
    public async Task Owned_work_order_gets_the_message()
    {
        TenantOwns("od-42");
        _oneCore.Setup(x => x.UpdateWorkOrder(It.IsAny<UpdateWorkOrderCommand>()))
            .ReturnsAsync(WorkOrderCommandStatus.Success);

        var response = await CreateHandler().Handle(new UpdateWorkOrderCommand("42", "Hej \"där\"\nrad två"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.Success, response.Status);
        Assert.True(response.Success);
        _oneCore.Verify(x => x.UpdateWorkOrder(It.Is<UpdateWorkOrderCommand>(c => c.WorkOrderId == "42" && c.Message == "Hej \"där\"\nrad två")), Times.Once);
    }

    [Fact]
    public async Task Core_failure_is_UpstreamFailed()
    {
        TenantOwns("od-42");
        _oneCore.Setup(x => x.UpdateWorkOrder(It.IsAny<UpdateWorkOrderCommand>()))
            .ReturnsAsync(WorkOrderCommandStatus.UpstreamFailed);

        var response = await CreateHandler().Handle(new UpdateWorkOrderCommand("42", "Hej"), CancellationToken.None);

        Assert.Equal(WorkOrderCommandStatus.UpstreamFailed, response.Status);
        Assert.False(response.Success);
    }
}
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj
```

Expected: `CS1729: 'UpdateWorkOrderCommandHandler' does not contain a constructor that takes 4 arguments`.

- [ ] **Step 3: Implement**

`UpdateWorkOrderCommandHandler.cs` (replace whole file; it stays `public`, as it is today):

```csharp
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Common.Exceptions;
using Application.Common.Infrastructure;
using Core.Crossccutting;
using MediatR;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;

namespace Application.Business.WorkOrder.Commands.UpdateWorkOrder;

public class UpdateWorkOrderCommandHandler : IRequestHandler<UpdateWorkOrderCommand, UpdateWorkOrderResponse>
{
    private const string OneCoreWorkOrderCodePrefix = "od-";

    private readonly IConfiguration _configuration;
    private readonly ILogger<UpdateWorkOrderCommandHandler> _logger;
    private readonly IOneCoreWorkOrderService _oneCoreService;
    private readonly ICurrentUser _currentUser;

    public UpdateWorkOrderCommandHandler(
        IConfiguration configuration,
        ILogger<UpdateWorkOrderCommandHandler> logger,
        IOneCoreWorkOrderService oneCoreService,
        ICurrentUser currentUser)
    {
        _configuration = configuration;
        _logger = logger;
        _oneCoreService = oneCoreService;
        _currentUser = currentUser;
    }

    public async Task<UpdateWorkOrderResponse> Handle(UpdateWorkOrderCommand request,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        var isOneCoreWorkOrdersEnabled = _configuration["FeatureManagement:OneCoreWorkOrders"];

        if (isOneCoreWorkOrdersEnabled.ToLower() != "true")
        {
            throw new NotImplementedException("OneCoreWorkOrders are not enabled");
        }

        if (!_currentUser.IsAuthenticated || string.IsNullOrEmpty(_currentUser.ContactCode))
        {
            throw new UnauthorizedException("User is unauthorized");
        }

        var tenantWorkOrders = await _oneCoreService.TryGetWorkOrdersByContactCode(_currentUser.ContactCode);

        if (tenantWorkOrders is null)
        {
            return Result(WorkOrderCommandStatus.UpstreamFailed, "Could not verify work order ownership");
        }

        var workOrderCode = OneCoreWorkOrderCodePrefix + request.WorkOrderId;
        var isOwnWorkOrder = tenantWorkOrders.WorkOrders
            .Any(x => string.Equals(x.Code, workOrderCode, StringComparison.OrdinalIgnoreCase));

        if (!isOwnWorkOrder)
        {
            _logger.LogWarning("User {ContactCode} tried to add a message to work order {WorkOrderId} they do not own",
                _currentUser.ContactCode, request.WorkOrderId);
            return Result(WorkOrderCommandStatus.Forbidden, "You do not have access to the resource");
        }

        var status = await _oneCoreService.UpdateWorkOrder(request);

        return status == WorkOrderCommandStatus.Success
            ? Result(status, "Work order updated")
            : Result(status, "Failed to update work order");
    }

    private static UpdateWorkOrderResponse Result(WorkOrderCommandStatus status, string message) =>
        new()
        {
            Status = status,
            Success = status == WorkOrderCommandStatus.Success,
            Message = message
        };
}
```

- [ ] **Step 4: Run, expect PASS**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj     # Passed: 25
dotnet build mimer-api.sln                       # 0 Error(s)
```

- [ ] **Step 5: Commit**

```sh
git add -A src tests
git commit -m "Only let tenants add messages to their own work orders

UpdateWorkOrderCommandHandler applies the same ownership check as close and
reports core failures instead of swallowing them.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task A5: WorkOrdersController returns real results; CloseWorkOrderRequest DTO

**Files:**
- Create: `src/WebApi/Models/CloseWorkOrderRequest.cs`
- Modify: `src/WebApi/Controllers/WorkOrdersController.cs` (add a using after line 16; replace lines 106-150, the `Close` and `Update` actions with their doc comments)
- Create (test): `tests/Api.Tests/WorkOrders/WorkOrdersControllerTests.cs`

**Interfaces:**
- Consumes: `CloseWorkOrderResponse.Status`, `UpdateWorkOrderResponse.Status` (A2-A4)
- Produces: `POST ~/api/workorders/close/{workOrderId}` body `CloseWorkOrderRequest { string? Reason }` (body optional) → 204 / 403 / 409 / 502; `POST ~/api/workorders/update/{workOrderId}` → 204 / 403 / 502; errors are `ProblemDetails` with `detail` = handler message, the same shape `UseProblemDetailsForApi` gives for exceptions; `closeRequestPending` in the work-order list JSON

- [ ] **Step 1: Write the failing test**

`tests/Api.Tests/WorkOrders/WorkOrdersControllerTests.cs`:

```csharp
using Application.Business.WorkOrder.Commands.CloseWorkOrder;
using Application.Business.WorkOrder.Commands.Shared.Models;
using Application.Business.WorkOrder.Commands.UpdateWorkOrder;
using Application.Business.WorkOrder.Queries.GetWorkOrders;
using System.Text.Json;
using MediatR;
using Microsoft.AspNetCore.Mvc;
using Moq;
using WebApi.Controllers;
using WebApi.Models;
using Xunit;

namespace Api.Tests.WorkOrders;

public class WorkOrdersControllerTests
{
    private readonly Mock<IMediator> _mediator = new();

    private void CloseReturns(WorkOrderCommandStatus status) =>
        _mediator.Setup(x => x.Send(It.IsAny<CloseWorkOrderCommand>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CloseWorkOrderResponse { Status = status, Success = status == WorkOrderCommandStatus.Success });

    private void UpdateReturns(WorkOrderCommandStatus status) =>
        _mediator.Setup(x => x.Send(It.IsAny<UpdateWorkOrderCommand>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new UpdateWorkOrderResponse { Status = status, Success = status == WorkOrderCommandStatus.Success });

    private static int? StatusOf(ActionResult result) => result switch
    {
        ObjectResult o => o.StatusCode,
        StatusCodeResult s => s.StatusCode,
        _ => null
    };

    [Theory]
    [InlineData(WorkOrderCommandStatus.Success, 204)]
    [InlineData(WorkOrderCommandStatus.Forbidden, 403)]
    [InlineData(WorkOrderCommandStatus.Conflict, 409)]
    [InlineData(WorkOrderCommandStatus.UpstreamFailed, 502)]
    public async Task Close_maps_handler_status_to_http_status(WorkOrderCommandStatus status, int expected)
    {
        CloseReturns(status);

        var result = await new WorkOrdersController(_mediator.Object)
            .Close("42", new CloseWorkOrderRequest { Reason = "Klart" });

        Assert.Equal(expected, StatusOf(result));
    }

    [Fact]
    public async Task Close_passes_reason_to_command_and_accepts_missing_body()
    {
        CloseReturns(WorkOrderCommandStatus.Success);
        var controller = new WorkOrdersController(_mediator.Object);

        await controller.Close("42", new CloseWorkOrderRequest { Reason = "Klart" });
        await controller.Close("43", null);

        _mediator.Verify(x => x.Send(It.Is<CloseWorkOrderCommand>(c => c.WorkOrderId == "42" && c.Reason == "Klart"), It.IsAny<CancellationToken>()), Times.Once);
        _mediator.Verify(x => x.Send(It.Is<CloseWorkOrderCommand>(c => c.WorkOrderId == "43" && c.Reason == null), It.IsAny<CancellationToken>()), Times.Once);
    }

    [Theory]
    [InlineData(WorkOrderCommandStatus.Success, 204)]
    [InlineData(WorkOrderCommandStatus.Forbidden, 403)]
    [InlineData(WorkOrderCommandStatus.Conflict, 502)]
    [InlineData(WorkOrderCommandStatus.UpstreamFailed, 502)]
    public async Task Update_maps_handler_status_to_http_status(WorkOrderCommandStatus status, int expected)
    {
        UpdateReturns(status);

        var result = await new WorkOrdersController(_mediator.Object)
            .Update("42", new UpdateWorkOrderRequest { Message = "Hej" });

        Assert.Equal(expected, StatusOf(result));
    }

    [Fact]
    public void WorkOrderResponse_serializes_CloseRequestPending_as_camelCase_for_mina_sidor()
    {
        var json = JsonSerializer.Serialize(
            new WorkOrderResponse { Code = "od-42", CloseRequestPending = true },
            new JsonSerializerOptions(JsonSerializerDefaults.Web));

        Assert.Contains("\"closeRequestPending\":true", json);
    }
}
```

- [ ] **Step 2: Run it, expect FAIL**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj
```

Expected: `CS0246: The type or namespace name 'CloseWorkOrderRequest' could not be found` and
`CS1501: No overload for method 'Close' takes 2 arguments`.

- [ ] **Step 3: Implement**

`src/WebApi/Models/CloseWorkOrderRequest.cs` (new):

```csharp
namespace WebApi.Models;

public class CloseWorkOrderRequest
{
    /// <summary>
    /// Optional reason the tenant gives for wanting the work order closed (max 500 characters)
    /// </summary>
    public string? Reason { get; set; }
}
```

`WorkOrdersController.cs`: after line 16 (`using Microsoft.AspNetCore.Mvc;`) add
`using Microsoft.AspNetCore.Mvc.ModelBinding;` (for `EmptyBodyBehavior`). `WorkOrderCommandStatus` is already in
scope through `using Application.Business.WorkOrder.Commands.Shared.Models;` on line 6. Replace lines 106-150 (from
`/// <summary>` / `/// Close work order` up to the closing brace of `Update`) with:

```csharp
    /// <summary>
    /// Request that a work order is closed
    /// </summary>
    /// <remarks>
    /// Auth required, can only act on the logged-in tenant's own ONECore work orders.
    /// Sends a close request to whoever handles the work order; it is not closed until they accept.
    /// </remarks>
    /// <param name="workOrderId">Id of the work order (the ONECore code without the "od-" prefix)</param>
    /// <param name="request">Optional reason for the close request</param>
    /// <returns>No content</returns>
    /// <response code="204">Close request sent</response>
    /// <response code="400">Bad request</response>
    /// <response code="401">Not authorized</response>
    /// <response code="403">The work order does not belong to the logged-in tenant</response>
    /// <response code="409">A close request is already pending, or the work order is closed or hidden</response>
    /// <response code="502">ONECore could not be reached or failed</response>
    [HttpPost("~/api/workorders/close/{workOrderId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status403Forbidden)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status409Conflict)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status502BadGateway)]
    public async Task<ActionResult> Close(
        [FromRoute] string workOrderId,
        [FromBody(EmptyBodyBehavior = EmptyBodyBehavior.Allow)] CloseWorkOrderRequest? request)
    {
        var response = await _mediator.Send(new CloseWorkOrderCommand(
            workOrderId,
            request?.Reason
        ));

        return response.Status switch
        {
            WorkOrderCommandStatus.Success => NoContent(),
            WorkOrderCommandStatus.Forbidden => Problem(detail: response.Message, statusCode: StatusCodes.Status403Forbidden),
            WorkOrderCommandStatus.Conflict => Problem(detail: response.Message, statusCode: StatusCodes.Status409Conflict),
            _ => Problem(detail: response.Message, statusCode: StatusCodes.Status502BadGateway)
        };
    }

    /// <summary>
    /// Update work order with a message
    /// </summary>
    /// <remarks>
    /// Auth required, can only act on the logged-in tenant's own ONECore work orders.
    /// Adds a message to a work order
    /// </remarks>
    /// <param name="workOrderId">Id of the work order (the ONECore code without the "od-" prefix)</param>
    /// <param name="request">Update work order request</param>
    /// <returns>No content</returns>
    /// <response code="204">No content</response>
    /// <response code="400">Bad request</response>
    /// <response code="401">Not authorized</response>
    /// <response code="403">The work order does not belong to the logged-in tenant</response>
    /// <response code="502">ONECore could not be reached or failed</response>
    [HttpPost("~/api/workorders/update/{workOrderId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status403Forbidden)]
    [ProducesResponseType(typeof(ProblemDetails), StatusCodes.Status502BadGateway)]
    public async Task<ActionResult> Update([FromRoute] string workOrderId, [FromBody] UpdateWorkOrderRequest request)
    {
        var response = await _mediator.Send(new UpdateWorkOrderCommand(
            workOrderId,
            request.Message
        ));

        return response.Status switch
        {
            WorkOrderCommandStatus.Success => NoContent(),
            WorkOrderCommandStatus.Forbidden => Problem(detail: response.Message, statusCode: StatusCodes.Status403Forbidden),
            _ => Problem(detail: response.Message, statusCode: StatusCodes.Status502BadGateway)
        };
    }
```

`EmptyBodyBehavior.Allow` is explicit because .NET 6 MVC does not infer that a body is optional from `?`. Today's
Mina sidor posts `{}` with `Content-Type: application/json`, and that keeps working unchanged. The file is UTF-8
with BOM; keep it that way.

- [ ] **Step 4: Run, expect PASS**

```sh
dotnet test tests/Api.Tests/Api.Tests.csproj     # Passed: 35
dotnet build mimer-api.sln                       # 0 Error(s)
```

Optional manual check against the local stack (the `local-e2e` skill; OneCoreWorkOrders flag on): close a foreign
`od-` id and expect 403 with no core log line; close your own and expect 204; close it again and expect 409.

- [ ] **Step 5: Commit**

```sh
git add -A src tests
git commit -m "Return 204/403/409/502 from work order close and update endpoints

The close endpoint accepts an optional { reason } body. Both endpoints now
return the handler outcome instead of always answering 204.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### API: facts that contradict or sharpen the spec/contract

1. **No test project existed.** The spec's "handler tests" need A1 first. CI builds the test project but does not
   run it (no `dotnet test` step in the Azure pipelines).
2. **The ownership lookup needed a failure-aware variant.** The existing `GetWorkOrdersByContactCode` returns an empty
   list when core fails, which would turn "core down" into 403 instead of the spec's 502. A2 adds
   `TryGetWorkOrdersByContactCode`: same core endpoint, `null` on failure. The contract names no such method; it is
   internal to the API.
3. **Contact code source:** `ICurrentUser.ContactCode` (the JWT `ClaimTypes.Name`), which matches the contract's
   "from token". Admin/Developer tokens have no work orders of their own, so they now get 403 on close/update. Before,
   they could act on any id.
4. **Ownership is matched on `Code == "od-" + workOrderId`**, because Mina sidor strips `od-` before calling. Core's
   `id` field is the Odoo `uuid`, not the numeric id, so it cannot be used for this check.
5. **Hidden work orders pass the ownership check on purpose**, so closing one gives Odoo's `hidden` conflict (409) as
   the spec's error table says. Update on a hidden work order is still allowed, as today; the tenant cannot see it
   on Mina sidor anyway.
6. **Today core failures on close/update throw `NullReferenceException` (500)**, not "return false". Core's
   close/update bodies have no `content` wrapper. The spec's "Today both always return 204" is only true on success.
7. **The flag-off path answers 500, not 501.** `NotImplementedException` is not mapped in
   `ProblemDetailsApplicationBuilderExtensions`. Kept as is.
8. **`closeRequestPending` must be added to core's explicit mapping** in `GET /work-orders/by-contact-code`
   (`onecore/core/src/services/work-order-service/index.ts:316-341`). That route builds each object field by field,
   so a new `CloseRequestPending` on the work-order service's transform is dropped unless core maps it. Core emits
   camelCase (`closeRequestPending`). The API deserializes case-insensitively, so casing is not a problem, but the
   field must be there.
9. **Release-order hazard for the update path.** Once the API serializes the message properly, the current Mina
   sidor (which still sends `JSON.stringify(msg).slice(1, -1)`) will store literal `\n` and `\"` in tenant messages
   until the Webbappar change ships. The spec's order (API, then Webbappar) needs the two released back-to-back, or
   the update-body change held until the Webbappar release.
10. **`reason: null` must not be sent to core**, because Zod `optional()` rejects null. A2 omits the property when
    it is null (`WhenWritingNull`), so a close without a reason sends `{}`.
11. **Reason length:** the API enforces a 500-character maximum (400 above that) to match the spec's 500-character
    limit. The onecore and Odoo layers should either match it or not enforce it at all. The contract does not say
    which.

---

## Mina sidor (`mimer-nu/Webbappar/mina-sidor`)

**Branch:** `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` in `mimer-nu/Webbappar`
(it exists locally and currently equals the epic, `d4861922`). Before Task M1, rebase it onto
`epic/mim-1983-odoo-prioritized-ux-and-communication-improvements` *after* MIM-2040 (`c62a7fa3`) has been
merged there. Every line number below is the post-MIM-2040 state of the file.

**No unit-test setup exists in mina-sidor.** `package.json` has only `serve`, `build*` and `lint` scripts, there is no
jest/vitest dependency or config, and no `*.test.*`/`*.spec.*`/`tests/` in `mina-sidor/src`. These tasks add no test
framework. Verification is `pnpm run lint` plus `pnpm run build` plus the manual checklist in Task M3.

Two facts in this app shape the code below:

1. **A global axios interceptor in `src/main.js` (lines 19-41) hides error statuses from the stores.** It turns
   401/403/404/409 into `Promise.resolve()` (an **undefined** response), turns 500 into the generic `ErrorPrompt`
   plus a resolved error object, and rejects anything else (e.g. 502). With the interceptor, the store cannot see a
   409, because `response` is `undefined`. So `closeWorkOrder` and `updateWorkOrder` pass
   `validateStatus: () => true`. Axios then treats every HTTP status as success, the interceptor's error branch never
   runs, and the store reads `response.status` itself. Network failures (no response) still reject and end up in the
   store's `catch`.
2. **Styling comes from the external mimer.nu theme** (`public/index.html` links `https://test.mimer.nu/.../app.css`).
   There is no `tailwind.config.js`, so Tailwind variants such as `disabled:` are not available. The existing
   disabled-button pattern (`CreateWorkorder.vue:187`, `:220`) is `cursor-not-allowed` plus `style="opacity: 0.7"`,
   and the tasks below reuse it. The new message label gets its own rule in `WorkOrderMessage.css` rather than
   relying on theme classes that may not exist.

Errors are shown through `promptStore().displayErrorMessage(status, detail)` (`src/stores/prompt.js`), rendered
by `src/components/Common/ErrorPrompt.vue`: the fixed heading "Hoppsan, något gick fel!", the standard text
"Något gick fel. Var god försök igen senare…", and the detail string in a grey box. `WorkorderList.vue` already
calls it this way for close and update failures, and the tasks reuse it for both the 409 and the generic error.

---

### Task M1: Thread — tenant close request counts as the tenant, type labels, `closeRequestPending` on the work order

**Files:**
- Modify: `mina-sidor/src/stores/workorders.js` lines 5-22 (`transformWorkOrderMessage`, `transformWorkOrders`)
- Modify: `mina-sidor/src/components/WorkOrder/WorkOrderMessage.vue` lines 9-12 (template header row) and 21-24 (script)
- Modify: `mina-sidor/src/components/WorkOrder/WorkOrderMessage.css` (append)
- Test: none (no test framework, see above). Verified in Task M3.

**Interfaces:**
- Consumes: API `GET ~/api/applicants/me/workorders` → `workOrders[]` with `closeRequestPending` (bool, camelCase from
  `WorkOrderResponse.CloseRequestPending`) and `messages[].messageType` ∈ { …, `close_request_from_tenant`,
  `close_request_declined` } (the core adapter has these in `MESSAGE_DOMAIN`).
- Produces: every store work order has `closeRequestPending: boolean` (always a boolean; Xpand work orders get
  `false`). A message has `fromTenant: true` and `authorDisplayName: 'Du'` for `from_tenant` **and**
  `close_request_from_tenant`. `WorkOrderMessage` shows the label "Begäran om avslut" / "Avslutsbegäran avböjd".

- [ ] **Step 1: Replace the message and work-order transforms.** In `mina-sidor/src/stores/workorders.js`, keep the
  MIM-2040 comment (lines 5-10) as it is and replace lines 11-22:

  ```js
  const transformWorkOrderMessage = (message) => ({
      ...message,
      fromTenant: message.messageType === 'from_tenant',
      authorDisplayName: message.messageType === 'from_tenant' ? 'Du' : message.author,
      createDate: new Date(message.createDate),
  });

  const transformWorkOrders = (workOrders) =>
      workOrders.map((workOrder) => ({
          ...workOrder,
          messages: workOrder.messages.map(transformWorkOrderMessage),
      }));
  ```

  with:

  ```js
  // MIM-2036: a close request is posted by the integration on the tenant's
  // behalf, so it is shown as the tenant's own message ("Du", orange avatar).
  const TENANT_MESSAGE_TYPES = ['from_tenant', 'close_request_from_tenant'];

  const transformWorkOrderMessage = (message) => {
      const fromTenant = TENANT_MESSAGE_TYPES.includes(message.messageType);
      return {
          ...message,
          fromTenant,
          authorDisplayName: fromTenant ? 'Du' : message.author,
          createDate: new Date(message.createDate),
      };
  };

  const transformWorkOrders = (workOrders) =>
      workOrders.map((workOrder) => ({
          ...workOrder,
          // Only Odoo work orders can have a close request; Xpand ones come back false.
          closeRequestPending: workOrder.closeRequestPending === true,
          messages: workOrder.messages.map(transformWorkOrderMessage),
      }));
  ```

- [ ] **Step 2: Add the type label to the message header.** In
  `mina-sidor/src/components/WorkOrder/WorkOrderMessage.vue`, replace lines 9-12:

  ```html
              <div class="flex items-center">
                  <b class="mr-4">{{ message.authorDisplayName }}</b>
                  <span class="text-gray-500 text-sm"> - {{ formatDate }}</span>
              </div>
  ```

  with:

  ```html
              <div class="flex items-center flex-wrap">
                  <b class="mr-4">{{ message.authorDisplayName }}</b>
                  <span class="text-gray-500 text-sm"> - {{ formatDate }}</span>
                  <span v-if="typeLabel" class="message-type-label">{{ typeLabel }}</span>
              </div>
  ```

  Then replace lines 18-24 of the script:

  ```js
  <script>
  import './WorkOrderMessage.css';

  export default {
      props: ['message'],

      computed: {
  ```

  with:

  ```js
  <script>
  import './WorkOrderMessage.css';

  const MESSAGE_TYPE_LABELS = {
      close_request_from_tenant: 'Begäran om avslut',
      close_request_declined: 'Avslutsbegäran avböjd',
  };

  export default {
      props: ['message'],

      computed: {
          typeLabel() {
              return MESSAGE_TYPE_LABELS[this.message.messageType] || null;
          },
  ```

  (`formatDate()` stays unchanged below it.)

- [ ] **Step 3: Style the label.** Append to `mina-sidor/src/components/WorkOrder/WorkOrderMessage.css`:

  ```css

  .message-type-label {
      margin-left: 0.5rem;
      padding: 0 0.5rem;
      border-radius: 3px;
      font-size: 0.75rem;
      line-height: 1.25rem;
      background-color: #f3f4f6;
      color: #374151;
  }
  ```

- [ ] **Step 4: Lint the three files.**

  ```sh
  cd mimer-nu/Webbappar/mina-sidor
  pnpm run lint -- --no-fix
  ```

  Expected: `No lint errors found!`. (`vue-cli-service lint` auto-fixes by default. `--no-fix` only reports. If it
  reports formatting, run `pnpm run lint` and check the diff.)

- [ ] **Step 5: Commit.**

  ```sh
  cd mimer-nu/Webbappar
  git add mina-sidor/src/stores/workorders.js mina-sidor/src/components/WorkOrder/WorkOrderMessage.vue mina-sidor/src/components/WorkOrder/WorkOrderMessage.css
  git commit -m "$(cat <<'EOF'
  MIM-2036: show close requests and declines in the work order thread

  close_request_from_tenant is rendered as the tenant's own message, and both
  new message types get a small label. Work orders expose closeRequestPending.

  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task M2: Close request flow — store actions with status handling, per-card dialog state, pending button, refetch

**Files:**
- Modify: `mina-sidor/src/stores/workorders.js` lines 161-191 (`closeWorkOrder`, `updateWorkOrder`), plus one helper
  above `export const workordersStore` (after the transforms from M1)
- Modify: `mina-sidor/src/views/WorkorderList.vue` lines 81-145 (update/close block in the template), 189-195
  (`data`), 229-318 (`methods`)
- Test: none (no test framework). Verified in Task M3.

**Interfaces:**
- Consumes: API `POST ~/api/workorders/close/{workOrderId}` body `{ reason?: string }` → 204 / 403 / 409 / 502;
  API `POST ~/api/workorders/update/{workOrderId}` body `{ message }` → 204 / 403 / 502; `closeRequestPending` from M1.
- Produces: store `closeWorkOrder(workOrderId, reason)` → `{ ok: true } | { ok: false, conflict: boolean }`;
  store `updateWorkOrder(workOrderId, message)` → `{ ok: boolean }`, sending the message unmodified.

The old view kept one page-wide `workOrderDialogState` and one `message`. Every `<li>` is rendered (only the expanded
one is visible, through `v-show`), so every card with the dialog open mounted a textarea writing to the same `message`.
Text typed on one card and cancelled was then sent from another card that was submitted untouched. The new state is
three objects keyed by `workorder.code`. Vue 3's proxy reactivity makes new keys reactive without `$set`.

- [ ] **Step 1: Store — status-aware close and update.** In `mina-sidor/src/stores/workorders.js`, directly above
  `export const workordersStore = defineStore(` (after `transformWorkOrders`), add:

  ```js
  // The global axios interceptor in main.js resolves 403/404/409 to an undefined
  // response and turns 500 into a generic prompt, so a store can never see those
  // statuses. Calls that must tell a conflict from a failure accept every status
  // and check response.status themselves.
  const acceptAnyStatus = (config) => ({ ...config, validateStatus: () => true });
  ```

  Replace lines 161-191 (from `async closeWorkOrder(workOrderId) {` through the closing `},` of `updateWorkOrder`):

  ```js
          async closeWorkOrder(workOrderId) {
              try {
                  const response = await axios.post(
                      process.env.VUE_APP_API_BASE_URL + 'workorders/close/' + workOrderId,
                      {},
                      authStore().authConfig,
                  );

                  return response.status === 204;
              } catch (err) {
                  console.error('Error closing work order:', err);
                  return false;
              }
          },

          async updateWorkOrder(workOrderId, message) {
              try {
                  const response = await axios.post(
                      process.env.VUE_APP_API_BASE_URL + 'workorders/update/' + workOrderId,
                      {
                          message,
                      },
                      authStore().authConfig,
                  );

                  return response.status === 204;
              } catch (err) {
                  console.error('Error updating work order:', err);
                  return false;
              }
          },
  ```

  with:

  ```js
          // MIM-2036: this asks whoever handles the case to close it; it does not
          // close anything. 409 means a request is already pending, or the case was
          // closed or hidden in the meantime.
          async closeWorkOrder(workOrderId, reason) {
              const trimmedReason = typeof reason === 'string' ? reason.trim() : '';
              try {
                  const response = await axios.post(
                      process.env.VUE_APP_API_BASE_URL + 'workorders/close/' + workOrderId,
                      trimmedReason ? { reason: trimmedReason } : {},
                      acceptAnyStatus(authStore().authConfig),
                  );

                  if (response.status === 204) {
                      return { ok: true };
                  }
                  console.error('Error requesting close of work order:', response.status);
                  return { ok: false, conflict: response.status === 409 };
              } catch (err) {
                  console.error('Error requesting close of work order:', err);
                  return { ok: false, conflict: false };
              }
          },

          // The message is sent as typed: the API serializes the body to core
          // itself now, so it no longer needs pre-escaping here.
          async updateWorkOrder(workOrderId, message) {
              try {
                  const response = await axios.post(
                      process.env.VUE_APP_API_BASE_URL + 'workorders/update/' + workOrderId,
                      {
                          message,
                      },
                      acceptAnyStatus(authStore().authConfig),
                  );

                  if (response.status !== 204) {
                      console.error('Error updating work order:', response.status);
                  }
                  return { ok: response.status === 204 };
              } catch (err) {
                  console.error('Error updating work order:', err);
                  return { ok: false };
              }
          },
  ```

- [ ] **Step 2: View template — per-card dialog, pending button, reason field.** In
  `mina-sidor/src/views/WorkorderList.vue`, replace lines 81-145 (from
  `<div v-if="workOrderCanBeClosed(workorder) || workOrderCanBeUpdated(workorder)"` down to and including the
  closing `</div>` of the `workOrderDialogState === 'close'` block, i.e. everything before
  `<div v-if="workorder.messages.length > 0">`) with:

  ```html
                              <div
                                  v-if="workOrderCanBeClosed(workorder) || workOrderCanBeUpdated(workorder)"
                                  class="w-2/3 mx-auto">
                                  <div class="w-full bg-mimer-gray" style="height: 1px" />
                                  <h3 class="bison">Uppdatera ditt ärende</h3>
                                  <!-- .stop: a click on the disabled button must not collapse the card -->
                                  <div v-if="dialogState(workorder) === 'start'" @click.stop>
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-white bg-mimer-purple border-solid border-2 border-mimer-purple mt-4 rounded-lg no-underline mr-3"
                                          @click="setWorkOrderDialogState(workorder, 'update', $event)"
                                          aria-label="Jag vill komplettera med information">
                                          Jag vill komplettera med information
                                      </button>
                                      <button
                                          v-if="workOrderCanBeClosed(workorder)"
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-white bg-mimer-purple border-solid border-2 border-mimer-purple mt-4 rounded-lg no-underline"
                                          :class="{ 'cursor-not-allowed': workorder.closeRequestPending }"
                                          :style="workorder.closeRequestPending ? 'opacity: 0.7' : null"
                                          :disabled="workorder.closeRequestPending"
                                          @click="setWorkOrderDialogState(workorder, 'close', $event)"
                                          :aria-label="closeButtonLabel(workorder)">
                                          {{ closeButtonLabel(workorder) }}
                                      </button>
                                  </div>
                                  <div v-if="dialogState(workorder) === 'update'">
                                      <UpdateWorkOrderTextArea
                                          @click="onClickText($event)"
                                          @update:text="dialogTexts[workorder.code] = $event" />
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-white bg-mimer-purple border-solid border-2 border-mimer-purple rounded-lg no-underline mr-3"
                                          :disabled="submitting[workorder.code]"
                                          @click="onClickUpdateWorkOrder(workorder, $event)"
                                          aria-label="Skicka">
                                          Skicka
                                      </button>
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-mimer-purple bg-white border-solid border-2 border-mimer-purple rounded-lg no-underline"
                                          @click="setWorkOrderDialogState(workorder, 'start', $event)"
                                          aria-label="Avbryt">
                                          Avbryt
                                      </button>
                                  </div>
                                  <div v-if="dialogState(workorder) === 'updateDone'">
                                      <p>Tack för din info</p>
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-mimer-purple bg-white border-solid border-2 border-mimer-purple rounded-lg no-underline"
                                          @click="setWorkOrderDialogState(workorder, 'start', $event)"
                                          aria-label="Tillbaka">
                                          Tillbaka
                                      </button>
                                  </div>
                                  <div v-if="dialogState(workorder) === 'close'">
                                      <p>
                                          Din begäran om att avsluta ärendet skickas till den som handlägger det.
                                          Ärendet avslutas inte förrän begäran har godkänts, och svaret får du i
                                          kommunikationen nedan.
                                      </p>
                                      <p class="mt-4">Vill du berätta varför? (valfritt)</p>
                                      <UpdateWorkOrderTextArea
                                          @click="onClickText($event)"
                                          @update:text="dialogTexts[workorder.code] = $event" />
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-white bg-mimer-purple border-solid border-2 border-mimer-purple rounded-lg no-underline mr-3"
                                          :disabled="submitting[workorder.code]"
                                          @click="onClickCloseWorkOrder(workorder, $event)"
                                          aria-label="Skicka begäran om avslut">
                                          Skicka begäran om avslut
                                      </button>
                                      <button
                                          class="block md:inline-block lg:inline-block p-2 px-8 text-mimer-purple bg-white border-solid border-2 border-mimer-purple rounded-lg no-underline"
                                          @click="setWorkOrderDialogState(workorder, 'start', $event)"
                                          aria-label="Avbryt">
                                          Avbryt
                                      </button>
                                  </div>
  ```

  (`UpdateWorkOrderTextArea` already sets `maxlength="500"`, and it remounts with an empty text each time its `v-if`
  block is entered, which matches the reset in `setWorkOrderDialogState` below.)

- [ ] **Step 3: View script — state keyed by work order code.** Replace `data()` (lines 189-195):

  ```js
      data() {
          return {
              expanded: -1,
              workOrderDialogState: 'start',
              message: '',
          };
      },
  ```

  with:

  ```js
      data() {
          return {
              expanded: -1,
              // Keyed by work order code. Every card is rendered (only the expanded one
              // is visible), so page-wide dialog state leaks text between cards.
              dialogStates: {},
              dialogTexts: {},
              submitting: {},
              showingAll: false,
          };
      },
  ```

- [ ] **Step 4: View methods.** Replace `expandWorkOrder` (lines 232-235):

  ```js
          expandWorkOrder(workorderCode) {
              this.workOrderDialogState = 'start';
              this.expanded = this.expanded === workorderCode ? '-1' : workorderCode;
          },
  ```

  with:

  ```js
          expandWorkOrder(workorderCode) {
              this.dialogStates = {};
              this.dialogTexts = {};
              this.expanded = this.expanded === workorderCode ? '-1' : workorderCode;
          },
  ```

  Replace lines 273-318 (from `fetchAll() {` through the closing `},` of `setWorkOrderDialogState`) with:

  ```js
          fetchAll() {
              this.showingAll = true;
              this.fetchAllWorkorders();
          },

          async refreshWorkOrders() {
              try {
                  await (this.showingAll ? this.fetchAllWorkorders() : this.fetchWorkorders());
              } catch (err) {
                  console.error('Error refreshing work orders:', err);
              }
          },

          // MIM-2036: any Odoo case that is not closed, whatever its stage. The tenant
          // only asks; the person handling the case decides.
          workOrderCanBeClosed(workorder) {
              return workorder.code.startsWith('od-') && workorder.status !== 'Avslutad';
          },

          workOrderCanBeUpdated(workorder) {
              return workorder.code.startsWith('od-') && workorder.status !== 'Avslutad';
          },

          closeButtonLabel(workorder) {
              return workorder.closeRequestPending
                  ? 'Begäran om avslut skickad – väntar på svar'
                  : 'Jag vill avsluta ärendet';
          },

          dialogState(workorder) {
              return this.dialogStates[workorder.code] || 'start';
          },

          async onClickCloseWorkOrder(workorder, event) {
              event.stopPropagation();
              const code = workorder.code;
              if (this.submitting[code]) {
                  return;
              }
              this.submitting[code] = true;
              try {
                  const result = await this.closeWorkOrder(code.replace('od-', ''), this.dialogTexts[code]);
                  if (result.ok) {
                      this.dialogStates[code] = 'start';
                      this.dialogTexts[code] = '';
                      await this.refreshWorkOrders();
                  } else if (result.conflict) {
                      promptStore().displayErrorMessage(409, 'Det finns redan en begäran som väntar på svar');
                      this.dialogStates[code] = 'start';
                      this.dialogTexts[code] = '';
                      await this.refreshWorkOrders();
                  } else {
                      // Keep the dialog and the typed reason so the tenant can retry.
                      promptStore().displayErrorMessage(null, 'Kunde inte skicka begäran om avslut.');
                  }
              } finally {
                  this.submitting[code] = false;
              }
          },

          async onClickUpdateWorkOrder(workorder, event) {
              event.stopPropagation();
              const code = workorder.code;
              if (this.submitting[code]) {
                  return;
              }
              this.submitting[code] = true;
              try {
                  const result = await this.updateWorkOrder(code.replace('od-', ''), this.dialogTexts[code] || '');
                  if (!result.ok) {
                      promptStore().displayErrorMessage(null, 'Kunde inte uppdatera ärendet.');
                  } else {
                      this.dialogStates[code] = 'updateDone';
                      this.dialogTexts[code] = '';
                      await this.refreshWorkOrders();
                  }
              } finally {
                  this.submitting[code] = false;
              }
          },

          onClickText(event) {
              event.stopPropagation();
          },

          setWorkOrderDialogState(workorder, state, event) {
              event.stopPropagation();
              this.dialogStates[workorder.code] = state;
              this.dialogTexts[workorder.code] = '';
          },
  ```

  This removes `window.location.reload()` and the `JSON.stringify(this.message).slice(1, -1)` workaround. After a
  successful or conflicting request the card stays expanded (`expanded` is keyed by code and the refetched `<li>`
  keeps its `:key`), so the tenant sees the disabled "Begäran om avslut skickad – väntar på svar" button and the
  "Begäran om avslut" message appear in place.

- [ ] **Step 5: Confirm nothing still references the removed state.**

  ```sh
  cd mimer-nu/Webbappar/mina-sidor
  grep -n "workOrderDialogState\|this\.message\b\|window.location.reload\|JSON.stringify" src/views/WorkorderList.vue
  ```

  Expected: no output.

- [ ] **Step 6: Lint.**

  ```sh
  pnpm run lint -- --no-fix
  ```

  Expected: `No lint errors found!`

- [ ] **Step 7: Commit.**

  ```sh
  cd mimer-nu/Webbappar
  git add mina-sidor/src/stores/workorders.js mina-sidor/src/views/WorkorderList.vue
  git commit -m "$(cat <<'EOF'
  MIM-2036: let tenants request closing a work order instead of closing it

  The close button is shown for every open Odoo case and becomes a request
  with an optional reason; it is disabled while a request is pending. The
  stores read the response status directly (bypassing the global interceptor)
  so a 409 can be told apart from a failure, the page refetches instead of
  reloading, dialog state is kept per work order, and update messages are sent
  unmodified now that the API serializes the body.

  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

### Task M3: Verify — lint, build, manual run against the local stack

**Files:** none modified (read-only verification). If lint auto-fixes anything, commit it as
`MIM-2036: apply lint fixes` with the same `Co-Authored-By` trailer.

**Interfaces:**
- Consumes: the local stack with the MIM-2036 changes from the other repos. That means Odoo 19 with the updated
  `onecore-odoo` addons installed and module-upgraded; `onecore` `@onecore/work-order` + `@onecore/core`; the .NET
  API (`https://localhost:5001`, `FeatureManagement:OneCoreWorkOrders=true`, temporary CORS for
  `http://localhost:3000` as in `mimer-nu/API/README.md`); the SSH tunnel to Xpand for reads. Use the workspace
  `local-e2e` skill for the startup recipe and the cleanup rule.
- Produces: evidence per acceptance item below.

- [ ] **Step 1: Static checks.**

  ```sh
  cd mimer-nu/Webbappar/mina-sidor
  pnpm install
  pnpm run lint -- --no-fix
  pnpm run build
  ```

  Expected: `No lint errors found!`, and the build ends with `Build complete. The dist directory is ready to be
  deployed.` and no errors. (Size warnings are pre-existing.) Delete `mina-sidor/dist/` afterwards if it was not
  there before.

- [ ] **Step 2: Start Mina sidor against the local API.**

  ```sh
  cp .env.example .env   # already has VUE_APP_API_BASE_URL="https://localhost:5001/api/" and VUE_APP_ONE_CORE_WORK_ORDERS="true"
  pnpm run serve
  ```

  Open `https://localhost:5001/swagger` once in the same browser to accept the dev certificate. Then log in at
  `http://localhost:3000/mina-sidor/` as a test tenant (credentials: wiki page *Testmiljöer & testanvändare*) who has
  at least **two** open Odoo work orders (`od-…`), ideally in different stages (e.g. *Väntar på handläggning* and
  *Utförd*). If needed, create them first through *Felanmälan* with laundry/kitchen-appliance rows. Go to
  `http://localhost:3000/mina-sidor/serviceanmalningar`. Keep DevTools → Network open (filter `workorders`).

- [ ] **Step 3: Manual checklist.** Tick each item only after seeing it:

  1. **Button on every open Odoo case.** Expand an `od-` case in *Utförd* (or *Väntar på beställda varor*):
     "Jag vill avsluta ärendet" is visible. The old code hid it here. An Xpand case (no `od-` prefix) shows neither
     button. An *Avslutad* case shows neither button.
  2. **Dialog copy and reason.** Click "Jag vill avsluta ärendet". The text says the request goes to whoever handles
     the case and that the answer arrives in the thread. "Vill du berätta varför? (valfritt)" and a textarea are
     shown. The textarea stops at 500 characters (paste a longer text).
  3. **No leaking between cards.** Type `Test A` in card 1's close dialog and click *Avbryt*. Expand card 2, open
     "Jag vill komplettera med information" and click *Skicka* without typing. In Network, the
     `workorders/update/<id>` request body is `{"message":""}` and does not contain `Test A`. Repeat the other
     way round: type in card 2's update box, collapse, open card 1's close dialog. The textarea is empty.
  4. **Request with a reason.** On card 1, open the dialog, type `Klart nu, "tack" & <b>hej</b>` on two lines, and
     click *Skicka begäran om avslut*. Network: `POST workorders/close/<id>` with body
     `{"reason":"Klart nu, \"tack\" & <b>hej</b>\n…"}` → **204**. The page does **not** reload (the Network log is
     kept, with no document request). A `GET applicants/me/workorders` follows. The card stays expanded. The button
     reads "Begäran om avslut skickad – väntar på svar", is dimmed, and clicking it does nothing (the card does not
     collapse). The thread shows a new message from "Du" with an orange avatar, the label "Begäran om avslut", and the
     body "Begäran om att avsluta ärendet" / "Orsak: Klart nu, "tack" & <b>hej</b>" with the tags shown as text
     (escaped by Odoo) and the line break kept.
  5. **Request without a reason.** On card 2, send the dialog with an empty textarea. Network body is `{}` → 204.
     The thread message has no "Orsak:" line.
  6. **Pending survives reload.** Press F5. Both cards still show the disabled pending button (the value comes from
     `closeRequestPending` in the API response, not from local state). In Network, the response JSON for those work
     orders has `"closeRequestPending": true`.
  7. **409.** On card 1 (pending), force a second request. In DevTools console run
     `document.querySelectorAll('button[disabled]').forEach((b) => b.removeAttribute('disabled'))`, click the
     button, then click *Skicka begäran om avslut*. Network: 409. The error dialog "Hoppsan, något gick fel!" shows
     "Det finns redan en begäran som väntar på svar". Close it with ×. The card is back in the start state with the
     disabled pending button. There is no second "Begäran om avslut" message in the thread.
  8. **Decline.** In Odoo (`http://localhost:8069`) open card 1's request and click *Avslå*. Enter the reason
     `Delar är beställda` and confirm. Reload Mina sidor. The thread shows a staff message (green avatar, author
     "Mimer" or "Mimers Leverantör - …") labelled "Avslutsbegäran avböjd" with the body `Delar är beställda`. The button
     is enabled again and reads "Jag vill avsluta ärendet".
  9. **Request again, then accept.** Send a new request on card 1 → pending again. In Odoo click *Avsluta ärendet*.
     Reload Mina sidor. Card 1 now has status *Avslutad* and appears among the closed cases, with no buttons.
  10. **Generic error, button stays usable.** Stop `@onecore/core` (or the API's route to it) and send a request on
      card 2 after declining it in Odoo. The error dialog shows "Kunde inte skicka begäran om avslut.". After closing
      it, the close dialog is still open with the typed reason kept, and *Skicka begäran om avslut* is clickable
      again. Restart core.
  11. **Update path still works with special characters.** On an open case use "Jag vill komplettera med information"
      with `Rad 1 "citat"` + newline + `Rad 2 \ bakstreck`. The request body is exactly that string (no extra escaping)
      → 204. "Tack för din info" appears, and the new "Du" message in the thread shows the quotes, backslash and line
      break verbatim.
  12. **"Visa alla" is kept.** If the tenant has more than 10 work orders, click *Visa alla* and then send an update.
      The list still shows all work orders after the refetch.

- [ ] **Step 4: Clean up.** Stop `pnpm run serve` and every service, container and tunnel started for this check.
  Remove the temporary CORS change from the API's `Program.cs` (`git -C mimer-nu/API diff` shows nothing
  CORS-related). Remove `mina-sidor/.env` only if it was created in Step 2.

---

### Facts that contradict or sharpen the spec/contract

1. **The global axios interceptor (`mina-sidor/src/main.js:19-41`) makes a 409 invisible to the store by default.** It
   resolves 401/403/404/409 to `undefined`. The spec's "409 → Det finns redan…" is only possible because
   `validateStatus: () => true` is passed on these two calls (Task M2 Step 1). A 500 would otherwise also trigger the
   global prompt, and the view's own message would then be a second prompt.
2. **"Button stays enabled" on Odoo/core down (spec error table):** the API returns 502, and before this change
   the interceptor *rejected* it, so it reached the old `catch`. The new code handles 502 via `response.status` and
   keeps the dialog open. The behaviour matches the spec, but the mechanism differs from what the old code did.
3. **Removing the stringify hack must not ship before the API fix.** `mimer-nu/API` `main`
   `src/Infrastructure/OneCore/OneCoreWorkOrderService.cs:99` still builds the update body as
   `"{\"message\": \"" + request.Message + "\"}"`. If mina-sidor ships first, any update containing `"` or a newline
   produces invalid JSON towards core. The spec's release order (API before Webbappar) covers this. It is a hard
   dependency, not just the preferred order.
4. **Copy not fixed by the contract** was written in this plan and needs sign-off: the dialog text ("Din begäran om att
   avsluta ärendet skickas till den som handlägger det. Ärendet avslutas inte förrän begäran har godkänts, och
   svaret får du i kommunikationen nedan."), the reason prompt "Vill du berätta varför? (valfritt)", the confirm and
   cancel buttons "Skicka begäran om avslut" / "Avbryt" (replacing "Ja, jag vill avsluta mitt ärende" / "Nej, behåll
   mitt ärende", which promise closing), and the generic error detail "Kunde inte skicka begäran om avslut." (replacing
   "Kunde inte avsluta ärendet.").
5. **The contract's 409 copy has no trailing full stop** ("Det finns redan en begäran som väntar på svar"), while the
   existing error details end with one. The plan uses the contract copy verbatim.
6. **Styling:** mina-sidor has no Tailwind build of its own (no `tailwind.config.js`; CSS comes from the mimer.nu theme
   `app.css`), so Tailwind variants like `disabled:` in the spec's spirit cannot be relied on. The plan uses the app's
   existing `cursor-not-allowed` + `opacity: 0.7` pattern and a local CSS class for the label.
7. **After acceptance the tenant loses the thread:** the whole "Uppdatera ditt ärende" block, *including* "Kommunikation
   i detta ärende", sits inside `v-if="workOrderCanBeClosed || workOrderCanBeUpdated"` (`WorkorderList.vue:81-154`), so an
   *Avslutad* case shows no messages. This is pre-existing and was left unchanged. It means a tenant never sees
   messages on a closed case, which is harmless for "accepted → the stage change is enough" but worth knowing.
8. `workOrderCanBeClosed` and `workOrderCanBeUpdated` become the same rule. Both are kept for readability, as the spec
   words them separately.

---

### Task Z: End-to-end verification against the local stack

**Files:** none

- [ ] **Step 1: Run the workspace `local-e2e` skill** against the four branches: local Odoo with the new modules upgraded, work-order and core from the onecore branch, the API on :5001, and mina-sidor on :3000. Use real Xpand test data (reads only). Walk through this sequence:
  1. Send a request with a reason. The button disables, and the thread shows "Begäran om avslut" with the reason.
  2. In Odoo, the purple badge shows first on the kanban card and in the form.
  3. Decline the request with a reason. The decline shows on Mina sidor with the handler's sender, and the button is enabled again.
  4. Send a second request, then accept it. The case is *Avslutad*.
  5. Call `POST https://localhost:5001/api/workorders/close/<another tenant's od- id>` as the logged-in tenant. It returns 403.
  6. Log in to Odoo as a contractor user. Only *Avslå* is offered.
- [ ] **Step 2: Clean up.** Stop every service, database and browser session started for this run. Delete any throwaway database.
