# "Ny kundinfo" för alla Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the "Ny kundinfo" badge shared across all Mimer users and persistent (no auto-clear on open), cleared only via an adaptive shared "Markera som läst" acknowledge button.

**Architecture:** Re-model "Ny kundinfo" from a per-user inbox notification into a shared, audience-scoped unread flag (`has_unread_new_customer_info` + shared `new_customer_info_ack_at`), mirroring the existing master-key/supplier-dialog acknowledge pattern on `maintenance.request`. The existing single chatter "Markera som läst" button becomes adaptive: one unread signal → a specifically-labelled button that acks immediately; two or more → a generic button that opens a confirm-all dialog.

**Tech Stack:** Odoo 19 (Python models + OWL/JS + XML views), pytest-style Odoo `TransactionCase` tests.

## Global Constraints

- All user-facing text is in **Swedish**.
- Field definitions include `string=` in Swedish; use `store=True` only when persistence is needed.
- Follow existing patterns; do not invent new ones. The reference patterns are `_compute_has_unread_master_key_change` / `action_acknowledge_master_key_change` / `_compute_dialog_indicators` in `onecore_maintenance_extension/models/maintenance.py`.
- "Ny kundinfo" is **internal-Mimer only** — external contractors must never see or clear it.
- No tenant SMS/email in this version.
- Run Python tests with `./run_tests.sh` (requires `.env`). There is **no JS test harness** — JS/XML changes are verified manually.
- Do **not** commit the spec or this plan file (standing preference: planning docs under `docs/superpowers/` stay uncommitted).

**Spec:** `docs/superpowers/specs/2026-07-03-ny-kundinfo-for-alla-design.md`

## File Structure

- `onecore_maintenance_extension/models/maintenance.py` — add `new_customer_info_ack_at` field, `has_unread_new_customer_info` computed field + compute method, `action_acknowledge_new_customer_info`; remove the obsolete `new_mimer_notification` field + `_compute_new_mimer_notification`.
- `onecore_maintenance_extension/tests/models/test_new_customer_info_indicator.py` — new model tests (create).
- `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml` — kanban badge condition.
- `onecore_maintenance_extension/views/maintenance_views.xml` — kanban field decl (line 792) + form invisible field (line 112-116 header).
- `onecore_maintenance_extension/views/mobile_view.xml` — mobile field decl (line 49).
- `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js` — adaptive signal getters + confirm-dialog acknowledge flow.
- `onecore_mail_extension/static/src/tenant/tenant_chatter.xml` — adaptive button `t-if` + dynamic label + handler rename.

---

### Task 1: Backend — shared flag, compute, and acknowledge action

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py` (add fields near the master-key fields ~line 168-180; add compute method after `_compute_has_unread_master_key_change` ~line 495; add action after `action_acknowledge_master_key_change` ~line 533)
- Test: `onecore_maintenance_extension/tests/models/test_new_customer_info_indicator.py` (create)

**Interfaces:**
- Produces:
  - Field `new_customer_info_ack_at` (`fields.Datetime`, stored)
  - Field `has_unread_new_customer_info` (`fields.Boolean`, computed, non-stored)
  - Method `action_acknowledge_new_customer_info(self)` → returns `True`, sets shared `new_customer_info_ack_at = now` and clears `recently_added_tenant`
- Consumes: existing `ExternalContractorService(self.env).is_external_contractor()`, existing stored field `recently_added_tenant` (from `TenantFieldsMixin`)

**Detection note:** "New customer info" is detected from `mail.message` records authored by the `odoo@mimer.nu` integration user (the account through which Mina sidor posts tenant communications), replacing the old per-user `mail.notification` inbox lookup. Restrict to `message_type in ("comment", "email")` so internal tracking/log notes authored by that account are not counted. If field verification later shows Mina-sidor messages use a different `message_type`, adjust this filter — but do not remove the author filter.

- [ ] **Step 1: Write the failing tests**

Create `onecore_maintenance_extension/tests/models/test_new_customer_info_indicator.py`:

```python
"""Tests for the "Ny kundinfo" shared notification (MIM-1844)."""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


def _get_or_create_mimer_user(env):
    """The integration account Mina sidor posts tenant communications as."""
    user = env["res.users"].sudo().search([("login", "=", "odoo@mimer.nu")], limit=1)
    if not user:
        user = env["res.users"].sudo().create(
            {"name": "Mimer Integration", "login": "odoo@mimer.nu"}
        )
    return user


def _post_customer_info(request, mimer_user, body="Ny info från hyresgäst"):
    """Post a comment authored by odoo@mimer.nu, as Mina sidor would."""
    return request.with_user(mimer_user).message_post(
        body=body, message_type="comment", subtype_xmlid="mail.mt_comment"
    )


@tagged("onecore")
class TestHasUnreadNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.request = create_maintenance_request(self.env)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_internal_user_sees_unread_after_customer_message(self):
        _post_customer_info(self.request, self.mimer_user)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_external_contractor_never_sees_it(self):
        _post_customer_info(self.request, self.mimer_user)
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_no_customer_message_means_no_unread(self):
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_recently_added_tenant_raises_flag(self):
        self.request.recently_added_tenant = True
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_reading_record_does_not_clear_flag(self):
        # Regression vs the old per-user inbox behaviour: merely opening/reading
        # the record must NOT clear the shared flag.
        _post_customer_info(self.request, self.mimer_user)
        record = self._refresh(self.internal_user)
        _ = record.name  # simulate opening the form
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_new_message_after_ack_reappears(self):
        first = _post_customer_info(self.request, self.mimer_user)
        self.request.new_customer_info_ack_at = first.date + timedelta(seconds=1)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

        later = _post_customer_info(self.request, self.mimer_user, body="Mer info")
        later.date = self.request.new_customer_info_ack_at + timedelta(seconds=1)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)


@tagged("onecore")
class TestAcknowledgeNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.request = create_maintenance_request(self.env)
        _post_customer_info(self.request, self.mimer_user)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_ack_sets_shared_timestamp_and_clears_flag(self):
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_new_customer_info)

        record.action_acknowledge_new_customer_info()
        self.assertTrue(self.request.new_customer_info_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_ack_clears_recently_added_tenant(self):
        self.request.recently_added_tenant = True
        record = self._refresh(self.internal_user)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(self.request.recently_added_tenant)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_ack_invalidates_flag_without_manual_refresh(self):
        record = self.request.with_user(self.internal_user)
        self.assertTrue(record.has_unread_new_customer_info)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(record.has_unread_new_customer_info)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh`
Expected: FAIL — `AttributeError` / field `has_unread_new_customer_info` and method `action_acknowledge_new_customer_info` do not exist.

- [ ] **Step 3: Add the fields**

In `onecore_maintenance_extension/models/maintenance.py`, immediately after the `has_unread_master_key_change` field (ends ~line 180), add:

```python
    new_customer_info_ack_at = fields.Datetime(
        string="Ny kundinfo kvitterad",
        help="Senaste tidpunkt någon Mimer-handläggare kvitterade ny kundinfo. "
        "Delas av alla Mimer-användare som har tillgång till ärendet.",
    )
    has_unread_new_customer_info = fields.Boolean(
        string="Okvitterad ny kundinfo",
        compute="_compute_has_unread_new_customer_info",
        store=False,
    )
```

- [ ] **Step 4: Add the compute method**

In `maintenance.py`, after `_compute_has_unread_master_key_change` (ends ~line 495), add:

```python
    @api.depends(
        "message_ids.date",
        "message_ids.author_id",
        "message_ids.message_type",
        "new_customer_info_ack_at",
        "recently_added_tenant",
    )
    def _compute_has_unread_new_customer_info(self):
        # "Ny kundinfo" is the tenant -> Mimer channel (Mina sidor). Shared
        # across all Mimer users via one ack timestamp, and internal-only:
        # external contractors never see or clear tenant customer info.
        for record in self:
            record.has_unread_new_customer_info = False

        if not self:
            return

        if ExternalContractorService(self.env).is_external_contractor():
            return

        # No strict separation: a freshly-added tenant also counts as new
        # customer info. It contributes until acknowledged (the ack action
        # clears recently_added_tenant), so no timestamp comparison is needed.
        for record in self:
            if record.recently_added_tenant:
                record.has_unread_new_customer_info = True

        # Mina-sidor communications appear as messages authored by the
        # odoo@mimer.nu integration account. sudo() so classification does not
        # depend on the reader's right to see that user's login.
        mimer_user = (
            self.env["res.users"]
            .sudo()
            .search([("login", "=", "odoo@mimer.nu")], limit=1)
        )
        if not mimer_user:
            return

        messages = self.env["mail.message"].search(
            [
                ("model", "=", "maintenance.request"),
                ("res_id", "in", self.ids),
                ("author_id", "=", mimer_user.partner_id.id),
                ("message_type", "in", ["comment", "email"]),
            ]
        )
        latest_by_request = {}
        for message in messages:
            if not message.date:
                continue
            current = latest_by_request.get(message.res_id)
            if not current or message.date > current:
                latest_by_request[message.res_id] = message.date

        for record in self:
            latest = latest_by_request.get(record.id)
            if not latest:
                continue
            ack_at = record.new_customer_info_ack_at
            if not ack_at or latest > ack_at:
                record.has_unread_new_customer_info = True
```

- [ ] **Step 5: Add the acknowledge action**

In `maintenance.py`, after `action_acknowledge_master_key_change` (ends ~line 533), add:

```python
    def action_acknowledge_new_customer_info(self):
        """Mark "Ny kundinfo" read for every Mimer user of the request.

        Acknowledgement is one shared timestamp on the request — the first
        Mimer handler to click clears the badge for all Mimer users. External
        contractors never see or call this. Per "no strict separation", the
        tenant-onboarding flag is cleared too so the badge fully disappears.
        """
        self.ensure_one()
        self.new_customer_info_ack_at = fields.Datetime.now()
        if self.recently_added_tenant:
            self.recently_added_tenant = False
        # Non-stored computed field — force a recompute so the chatter button
        # and the kanban chip re-evaluate immediately.
        self.invalidate_recordset(["has_unread_new_customer_info"])
        return True
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `./run_tests.sh`
Expected: PASS — all tests in `test_new_customer_info_indicator.py` green; no regressions elsewhere.

- [ ] **Step 7: Commit**

```bash
git add onecore_maintenance_extension/models/maintenance.py onecore_maintenance_extension/tests/models/test_new_customer_info_indicator.py
git commit -m "feat: shared internal-only Ny kundinfo flag + ack action (MIM-1844)"
```

---

### Task 2: Kanban badge — switch to the shared flag and remove the obsolete field

**Files:**
- Modify: `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml:9`
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml:792`
- Modify: `onecore_maintenance_extension/views/mobile_view.xml:49`
- Modify: `onecore_maintenance_extension/models/maintenance.py` (remove `new_mimer_notification` field ~145-149 and `_compute_new_mimer_notification` ~315-337)

**Interfaces:**
- Consumes: `has_unread_new_customer_info` (from Task 1)
- Removes: `new_mimer_notification` (verified in Task 1 exploration to be referenced only in these four locations)

- [ ] **Step 1: Point the kanban card badge at the new flag**

In `maintenance_request_item.xml`, change line 9 from:

```xml
                <div t-if="record.new_mimer_notification.raw_value || record.recently_added_tenant.raw_value">
```

to:

```xml
                <div t-if="record.has_unread_new_customer_info.raw_value">
```

(Leave the `<span class="mimer-badge">Ny kundinfo</span>` text and styling unchanged.)

- [ ] **Step 2: Declare the new flag in both kanban view arches**

In `maintenance_views.xml`, replace line 792:

```xml
                    <field name="new_mimer_notification" />
```

with:

```xml
                    <field name="has_unread_new_customer_info" />
```

In `mobile_view.xml`, replace line 49:

```xml
        <field name="new_mimer_notification" />
```

with:

```xml
        <field name="has_unread_new_customer_info" />
```

(Leave the adjacent `recently_added_tenant` field declarations in place — that field still exists and is used by `_order`.)

- [ ] **Step 3: Remove the obsolete field and its compute**

In `maintenance.py`, delete the `new_mimer_notification` field definition (~lines 145-149):

```python
    new_mimer_notification = fields.Boolean(
        string="New Mimer Message",
        compute="_compute_new_mimer_notification",
        store=False,
    )
```

and delete the entire `_compute_new_mimer_notification` method (~lines 315-337, from `def _compute_new_mimer_notification(self):` through `record.new_mimer_notification = record.id in flagged_ids`).

- [ ] **Step 4: Verify no dangling references remain**

Run: `grep -rn "new_mimer_notification" onecore_maintenance_extension onecore_mail_extension`
Expected: no output (zero matches).

- [ ] **Step 5: Verify the module loads and tests still pass**

Run: `./run_tests.sh`
Expected: PASS — module upgrades cleanly (no view-load error from a missing field), all tests green.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/static/src/views/maintenance_request_item.xml onecore_maintenance_extension/views/maintenance_views.xml onecore_maintenance_extension/views/mobile_view.xml onecore_maintenance_extension/models/maintenance.py
git commit -m "feat: kanban Ny kundinfo badge uses shared flag; drop new_mimer_notification (MIM-1844)"
```

---

### Task 3: Adaptive acknowledge button (chatter)

**Files:**
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml` (form header, ~line 112-116)
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js`
- Modify: `onecore_mail_extension/static/src/tenant/tenant_chatter.xml`

**Interfaces:**
- Consumes: form record data fields `has_unread_supplier_dialog`, `has_unread_internal_dialog`, `has_unread_master_key_change`, `has_unread_new_customer_info`; RPC methods `action_acknowledge_dialog`, `action_acknowledge_master_key_change`, `action_acknowledge_new_customer_info`.

**Note:** No JS test harness exists in this repo — verification is manual (Step 5).

- [ ] **Step 1: Expose the new flag to the form/chatter**

In `maintenance_views.xml`, in the header `xpath` that already exposes the dialog flags (currently lines 113-115), add the new flag so the chatter can read it:

```xml
                <xpath expr="//header" position="inside">
                    <field name="has_unread_supplier_dialog" invisible="1" />
                    <field name="has_unread_internal_dialog" invisible="1" />
                    <field name="has_unread_master_key_change" invisible="1" />
                    <field name="has_unread_new_customer_info" invisible="1" />
                </xpath>
```

- [ ] **Step 2: Replace the acknowledge logic in the chatter patch**

In `tenant_chatter_patch.js`, replace the entire `async onClickAcknowledgeDialog() { ... }` method with the adaptive implementation below (getters + renamed handler). Keep the rest of the file (the save-before-action confirmation flow) unchanged.

```javascript
  // Unread acknowledge signals for the current viewer, in display order.
  // supplier/internal dialog collapse into one "Meddelande" signal (only one
  // is ever set for a given viewer). Labels/names are Swedish.
  _unreadAckSignals() {
    const data = this.props.record?.data ?? {};
    const signals = [];
    if (data.has_unread_supplier_dialog || data.has_unread_internal_dialog) {
      signals.push({
        name: _t("Meddelande"),
        buttonLabel: _t("Markera meddelande som läst"),
        method: "action_acknowledge_dialog",
      });
    }
    if (data.has_unread_master_key_change) {
      signals.push({
        name: _t("Huvudnyckeländring"),
        buttonLabel: _t("Markera huvudnyckeländring som läst"),
        method: "action_acknowledge_master_key_change",
      });
    }
    if (data.has_unread_new_customer_info) {
      signals.push({
        name: _t("Ny kundinfo"),
        buttonLabel: _t("Markera ny kundinfo som läst"),
        method: "action_acknowledge_new_customer_info",
      });
    }
    return signals;
  },

  showAckButton() {
    return (
      this.props.record?.resModel === "maintenance.request" &&
      this._unreadAckSignals().length > 0
    );
  },

  ackButtonLabel() {
    const signals = this._unreadAckSignals();
    return signals.length === 1 ? signals[0].buttonLabel : _t("Markera som läst");
  },

  async _acknowledgeSignals(signals) {
    const record = this.props.record;
    await Promise.all(
      signals.map((s) =>
        this.env.services.orm.call("maintenance.request", s.method, [
          [record.resId],
        ]),
      ),
    );
    // Reload so has_unread_* refresh -> the button relabels/hides.
    await record.load();
    // Re-fetch messages so is_dialog_unread_for_side re-serializes and the
    // orange highlight clears (acknowledging only changes computed flags on
    // existing messages, so fetchNewMessages() would not refresh them).
    await this.state?.thread?.fetchMessages();
  },

  async onClickAcknowledge() {
    const record = this.props.record;
    if (!record?.resId) {
      return;
    }
    const signals = this._unreadAckSignals();
    if (signals.length === 0) {
      return;
    }
    if (signals.length === 1) {
      await this._acknowledgeSignals(signals);
      return;
    }
    // Two or more unread signals: confirm acknowledging all of them.
    const names = signals.map((s) => s.name).join(", ");
    this.dialogService.add(ConfirmationDialog, {
      title: _t("Markera som läst"),
      body: _t("Vill du markera följande som läst?") + " " + names,
      confirmLabel: _t("Markera som läst"),
      cancelLabel: _t("Avbryt"),
      confirm: () => this._acknowledgeSignals(signals),
    });
  },
```

(`ConfirmationDialog`, `_t`, and `this.dialogService` are already imported/initialised in this file.)

- [ ] **Step 3: Make the button adaptive in the template**

In `tenant_chatter.xml`, replace the acknowledge button block (the `<button ... t-on-click="onClickAcknowledgeDialog">Markera som läst</button>`) with:

```xml
    <!-- Acknowledge button — adaptive: specific label when one signal is
         unread, generic + confirm dialog when several. -->
    <xpath expr="//button[hasclass('o-mail-Chatter-activity')]" position="after">
        <button class="btn btn-warning ms-1 align-self-center text-nowrap"
                t-if="showAckButton()"
                t-on-click="onClickAcknowledge">
            <t t-esc="ackButtonLabel()"/>
        </button>
    </xpath>
```

- [ ] **Step 4: Rebuild assets**

Run: restart the local Odoo / upgrade the `onecore_mail_extension` module so the JS/XML assets rebuild (e.g. `./run-local-odoo.sh` with `-u onecore_mail_extension`, per local setup).
Expected: no asset build errors.

- [ ] **Step 5: Manual verification**

On a `maintenance.request` form, as an **internal** user, verify:
- No unread signals → no acknowledge button.
- Exactly one unread (e.g. only Ny kundinfo) → button reads the specific label ("Markera ny kundinfo som läst") and clicking acks immediately, badge/button disappear, and the effect is shared (another internal user no longer sees it).
- Two+ unread (e.g. Ny kundinfo + Huvudnyckel ändrad) → button reads "Markera som läst"; clicking opens a confirm dialog listing both names; confirming clears both; cancelling changes nothing.

As an **external contractor**, verify the Ny kundinfo signal never appears and their button (for "Meddelande från Mimer" / master key) still behaves correctly.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/views/maintenance_views.xml onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js onecore_mail_extension/static/src/tenant/tenant_chatter.xml
git commit -m "feat: adaptive Markera som läst button incl. Ny kundinfo (MIM-1844)"
```

---

## Self-Review

**Spec coverage:**
- Shared `new_customer_info_ack_at` + `has_unread_new_customer_info` (internal-only), unread from `odoo@mimer.nu` messages or `recently_added_tenant` → Task 1. ✓
- `action_acknowledge_new_customer_info` sets shared ack + clears `recently_added_tenant` → Task 1. ✓
- Badge shows for all Mimer users, no auto-clear on open → Task 1 (shared flag, `test_reading_record_does_not_clear_flag`) + Task 2 (badge switch). ✓
- Internal-only / contractor cannot see or clear → Task 1 (`test_external_contractor_never_sees_it`) + compute guard. ✓
- Adaptive button (specific-when-one, general+confirm-when-many, all signal types) → Task 3. ✓
- Kanban badge switch + remove `new_mimer_notification` → Task 2. ✓
- No tenant SMS/email; no per-user ack; no checkbox popup → nothing added for these (out of scope). ✓

**Placeholder scan:** No TBD/TODO; every code step has concrete code. The only conditional note (`message_type` filter) is an explicit, documented verification point, not a placeholder.

**Type consistency:** `has_unread_new_customer_info`, `new_customer_info_ack_at`, and `action_acknowledge_new_customer_info` are named identically in the model (Task 1), the views (Task 2, Task 3 Step 1), and the JS `method` string (Task 3 Step 2). Button handler renamed consistently from `onClickAcknowledgeDialog` to `onClickAcknowledge` in both the JS (Task 3 Step 2) and the template (Task 3 Step 3).
