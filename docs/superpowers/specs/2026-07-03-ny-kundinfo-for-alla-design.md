# Design: "Ny kundinfo" för alla (MIM-1844)

**Ticket:** [MIM-1844](https://linear.app/mimer-onecore/issue/MIM-1844/ny-kundinfo-for-alla)
**Branch:** `feature/mim-1844-ny-kundinfo-for-alla`
**Date:** 2026-07-03

## Problem

The "Ny kundinfo" badge signals that a tenant (hyresgäst) has communicated in a
case via Mina sidor. Today it has three problems the ticket wants fixed:

1. It is driven by a **per-user inbox notification** (`new_mimer_notification`),
   so it only shows for followers/recipients — not for everyone at Mimer.
2. It **auto-clears the instant a user opens the case** (standard Odoo inbox
   read behaviour), so it disappears for that user before it has been dealt
   with — and there is no way to explicitly acknowledge it.
3. There is no shared "one person acknowledges for everyone" action.

## Decisions (from ticket discussion + brainstorming)

The ticket's original steps proposed per-user ("kvittera för mig") *and*
for-everyone ("kvittera för alla") acknowledgement, plus a tenant notification.
David's concluding comments simplify this: *"Det räcker med att en kvitterar för
alla till att börja med"* and *"Blir onödigt komplicerat annars."* Madde's
mockup showed a single "Bekräfta som läst" button. The following decisions were
confirmed with the assignee during brainstorming:

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Shared acknowledgement**, no per-user level | David: one ack-for-all is enough; avoid complexity |
| 2 | **Reuse the existing "Markera som läst" chatter button** — no separate per-notification buttons | Avoids the crowded "button per color" UX |
| 3 | **Adaptive button:** one unread → a *specific* labelled button that acks immediately; many unread → a *general* "Markera som läst" button that opens a confirm dialog to ack all | Removes the "one silent click cleared three different things" surprise, while still being one button when it matters |
| 4 | Applies to **all signal types** (supplier-dialog, master-key, ny-kundinfo), not just ny-kundinfo | Consistent button behaviour regardless of which signals are present |
| 5 | ~~**Internal-Mimer only** for ny-kundinfo~~ — **superseded 2026-08-18**: both audiences see it, with a **separate ack timestamp per side** (`new_customer_info_ack_at` / `new_customer_info_external_ack_at`) | The original decision was a regression vs. the pre-branch behaviour (a contractor with an unread inbox notification did see the badge), and contractors read the tenant's message in the same chatter — no ACL hides it. Splitting the ack keeps a contractor from suppressing the tenant's message for Mimer, mirroring `_compute_dialog_indicators`. `recently_added_tenant` stays internal-only: it is a Mimer data-quality flag, not tenant communication, and it drives `_order` for everyone. |
| 6 | **No tenant notification (SMS/email)** in this version | Simplest first version; can be a later ticket |
| 7 | **No strict separation** between the two ny-kundinfo signals — the button clears the badge whether it was raised by a Mina-sidor message or by `recently_added_tenant` | One "Ny kundinfo" concept for the user |

## Existing pattern being reused

The repo already has a single chatter button "Markera som läst"
(`onecore_mail_extension/static/src/tenant/tenant_chatter.xml`) whose handler
`onClickAcknowledgeDialog` (`tenant_chatter_patch.js`) acknowledges
**supplier-dialog + internal-dialog + master-key** in one click. Each
acknowledgement writes a **shared timestamp on the request**
(`supplier_dialog_ack_at`, `internal_dialog_ack_at`, `master_key_ack_at`), so
the first person to click clears the signal for the whole audience. The dialog
is **audience-split**: an internal handler acks `supplier_dialog_ack_at`, an
external contractor acks `internal_dialog_ack_at`
(`maintenance.py:action_acknowledge_dialog`). "Ny kundinfo" reuses this shape,
and the button becomes adaptive (below).

## Data model

Add to `maintenance.request`
(`onecore_maintenance_extension/models/maintenance.py`, alongside the master-key
fields ~line 168-180):

- **`new_customer_info_ack_at`** — `fields.Datetime`, stored. The shared
  acknowledgement timestamp. One per request; first Mimer user to acknowledge
  sets it for all Mimer users.
- **`has_unread_new_customer_info`** — `fields.Boolean`, computed, **non-stored**.
  Drives the badge and participates in the button's unread count.

No stored "event timestamp" field is needed — unread is computed from messages,
mirroring `_compute_dialog_indicators`.

### `_compute_has_unread_new_customer_info`

New `@api.depends(...)` compute. `has_unread_new_customer_info` is `True` when
**both**:

1. The viewer is an **internal Mimer user**
   (`not ExternalContractorService(self.env).is_external_contractor()`). Always
   `False` for external contractors.
2. There is an active, un-acknowledged "new customer info" signal — **either**:
   - a `mail.message` on the request **authored by `odoo@mimer.nu`** with
     `date > new_customer_info_ack_at` (or no ack yet) — the Mina-sidor
     communication signal (replaces the old `new_mimer_notification` search); **or**
   - `recently_added_tenant` is `True` (the acknowledge action clears this, so
     it stops contributing once acked).

Batched query over the recordset like `_compute_dialog_indicators`, not a
per-record loop, to keep kanban `web_read_group` cheap. Reuse the
`odoo@mimer.nu` author lookup from `_compute_new_mimer_notification`, keyed on
the shared ack timestamp instead of per-user `mail.notification.is_read`.

### `action_acknowledge_new_customer_info`

New method mirroring `action_acknowledge_master_key_change`:

```python
def action_acknowledge_new_customer_info(self):
    self.ensure_one()
    self.new_customer_info_ack_at = fields.Datetime.now()
    # No strict separation: the tenant-onboarding badge signal is cleared too.
    if self.recently_added_tenant:
        self.recently_added_tenant = False
    self.invalidate_recordset(["has_unread_new_customer_info"])
    return True
```

- Sets one shared timestamp → clears for all Mimer users.
- Clears `recently_added_tenant` so the badge fully disappears (decision #7).
  Note this also affects `_order` sorting (`maintenance.py:58`), which is
  acceptable — an acknowledged case need no longer sort as "recently added".
- Only internal users ever see the button, so only they call it.

## UI — adaptive acknowledge button

### Signals available to the chatter (per viewer)

Exposed as invisible fields on the form (`maintenance_views.xml` ~line 113-115,
next to the other `has_unread_*` flags), so the JS can read/count them:

| Signal key | Flag field | Specific button label | Ack RPC |
|---|---|---|---|
| `supplier` / `internal` dialog | `has_unread_supplier_dialog` / `has_unread_internal_dialog` | "Markera meddelande som läst" | `action_acknowledge_dialog` |
| master-key | `has_unread_master_key_change` | "Markera huvudnyckeländring som läst" | `action_acknowledge_master_key_change` |
| ny-kundinfo | `has_unread_new_customer_info` | "Markera ny kundinfo som läst" | `action_acknowledge_new_customer_info` |

A viewer sees at most: 3 for an internal user (dialog + master-key +
ny-kundinfo), 2 for an external contractor (internal-dialog + master-key).
`has_unread_supplier_dialog` and `has_unread_internal_dialog` are never both
true for the same viewer, so they collapse into one "meddelande" signal.

### Behaviour

In `tenant_chatter_patch.js`, add getters on the patched `Chatter`:

- **`_unreadAckSignals()`** — returns the list of currently-unread signal
  descriptors `{ label, ackMethod }` for this record, derived from the flag
  fields above.
- **`ackButtonLabel()`** — if exactly one signal, return its specific `label`;
  otherwise return the generic `"Markera som läst"`.
- **`showAckButton()`** — `_unreadAckSignals().length > 0`.

`tenant_chatter.xml`:

- Button `t-if="props.record?.resModel === 'maintenance.request' and showAckButton()"`.
- Button text bound to `ackButtonLabel()` (`t-esc`) instead of the hard-coded
  "Markera som läst".

`onClickAcknowledge` (rename of `onClickAcknowledgeDialog`):

- Let `signals = this._unreadAckSignals()`.
- **1 signal** → call that signal's `ackMethod` directly (no dialog).
- **≥2 signals** → open Odoo's `ConfirmationDialog` (already imported) with a
  body listing the labels ("Vill du markera följande som läst?" + bulleted
  labels). On confirm, `Promise.all` the relevant ack RPCs.
- After acking: `await record.load()` and `await this.state?.thread?.fetchMessages()`
  (same refresh as today) so flags recompute, the button hides/relabels, and
  the dialog message-highlight clears.

Because the existing ack RPCs are no-ops when nothing is unread for the caller,
calling the relevant ones is always safe.

### Kanban badge (`onecore_maintenance_extension`)

- `static/src/views/maintenance_request_item.xml:9-13` — change the "Ny
  kundinfo" badge condition from
  `record.new_mimer_notification.raw_value || record.recently_added_tenant.raw_value`
  to `record.has_unread_new_customer_info.raw_value`.
- Keep the `.mimer-badge` (light blue) styling — no color change.
- Ensure the kanban record spec includes `has_unread_new_customer_info`.

### Cleanup

- `new_mimer_notification` / `_compute_new_mimer_notification` become unused for
  the badge. Remove if nothing else references them (verify first); otherwise
  leave and stop using in the badge.

## Audience summary (after change)

| Notification | Internal Mimer sees / acks | External contractor sees / acks |
|---|---|---|
| Meddelande från leverantör | ✅ | ❌ |
| Meddelande från Mimer | ❌ | ✅ |
| Huvudnyckel ändrad | ✅ | ✅ (shared) |
| **Ny kundinfo** | ✅ | ❌ **(cannot see or clear)** |

## Out of scope

- Tenant SMS/email that "info has been read" (ticket step 3) — deferred.
- Per-user acknowledgement ("kvittera för mig", ticket step 2) — dropped per David.
- The 3-level checkbox popup from Madde's mockup (för mig / för alla / för kund)
  — replaced by the adaptive single button + plain ack-all confirm.

## Testing

Follow existing test style (`@tagged("onecore")`, `TransactionCase`,
`FakerMixin`). Model tests parallel
`tests/models/test_master_key_change_indicator.py`:

1. `has_unread_new_customer_info` is `True` for an internal user when an
   unacked `odoo@mimer.nu` message exists.
2. It is `False` for an external contractor in the same situation.
3. `action_acknowledge_new_customer_info` sets the shared ack → flag becomes
   `False` for all internal users.
4. A **new** `odoo@mimer.nu` message dated after the ack re-raises the flag.
5. `recently_added_tenant` alone raises the flag; acknowledging clears both the
   flag and `recently_added_tenant`.
6. Opening the record (reading it) no longer clears the flag (regression vs old
   per-user behaviour).

(Adaptive-button label/confirm logic is JS; there is no JS test harness in this
repo, so it is verified manually per `reference_testing_setup`.)

## Files touched

- `onecore_maintenance_extension/models/maintenance.py` — fields, compute, ack method (remove old `new_mimer_notification` if unused).
- `onecore_maintenance_extension/views/maintenance_views.xml` — invisible flag field.
- `onecore_maintenance_extension/static/src/views/maintenance_request_item.xml` — badge condition.
- `onecore_mail_extension/static/src/tenant/tenant_chatter.xml` — adaptive `t-if` + dynamic label.
- `onecore_mail_extension/static/src/tenant/tenant_chatter_patch.js` — signal getters, label, confirm-dialog flow.
- `onecore_maintenance_extension/tests/models/test_new_customer_info_indicator.py` — new tests.
