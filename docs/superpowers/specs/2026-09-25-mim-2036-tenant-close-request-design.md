# Design: Hyresgäst begär avslut av ärende via Mina sidor (MIM-2036)

**Ticket:** [MIM-2036](https://linear.app/mimer-onecore/issue/MIM-2036/hyresgast-avslutar-arende-via-mina-sidor-mekanism)
**Epic:** [MIM-1983](https://linear.app/mimer-onecore/issue/MIM-1983/epic-odoo-prioritized-ux-and-communication-improvements)
**Date:** 2026-09-25
**Status:** spec approved 2026-09-25; amended during planning (see *Amendments from planning*)

| Repo | Branch | Base / PR target |
|---|---|---|
| onecore-odoo | `feat/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` | `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements` |
| onecore | `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` | `epic/mim-1983` |
| mimer-nu/API | `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` | `epic/mim-1983-odoo-prioritized-ux-and-communication-improvements` |
| mimer-nu/Webbappar | `feature/mim-2036-hyresgast-avslutar-arende-via-mina-sidor-mekanism` | `epic/mim-1983-odoo-prioritized-ux-and-communication-improvements` |

MIM-2040 (tenant-facing sender on messages) touches the same message-author code
in `odoo-adapter/utils.ts`, `WorkOrderMessage.vue` and `workorders.js`. The
MIM-2036 branches are rebased onto their epics after MIM-2040 has landed there,
before implementation starts.

## Problem

A tenant can already close an Odoo work order from Mina sidor: "Jag vill avsluta
ärendet" moves it straight to *Avslutad*, for cases in *Väntar på handläggning*,
*Resurs tilldelad* or *Påbörjad*. Verksamheten does not want the tenant to decide
that — a case with ordered parts or half-done work must not silently close. The
**Odoo user** decides; the tenant can only ask, regardless of stage.

## Decisions

| Question | Decision | Source |
|---|---|---|
| Does the tenant see their own request? | Yes, echoed in the thread on Mina sidor | Ticket comment, answer 1 |
| Repeat requests? | Button disabled while a request is pending | Answer 2 |
| Feedback on the outcome? | Accepted → the stage change is enough. Declined → a required reason, shown to the tenant | Answer 3 |
| Own label or reuse "Meddelande från kund"? | Own badge, "Hyresgäst vill avsluta" | Answer 4 |
| What ends "pending"? | An explicit decision in Odoo (Avsluta / Avslå), or the case reaching *Avslutad* any other way | Design discussion |
| Who decides? | Anyone with access to the case, contractors included, within their existing stage rules | Design discussion |
| Where does "pending" live? | Odoo, as a field on `maintenance.request`, exposed through the chain | Design discussion |
| Tenant can add a reason? | Yes, optional, 500 characters | Design discussion |
| Which cases show the button? | Every Odoo case (`od-` code) not in *Avslutad* | Ticket: "oavsett status" |
| Fix ownership check and swallowed errors on close/update? | Yes, in this ticket | Design discussion |

### Consequence of the contractor rule

`external_contractor_service.validate_stage_transition` forbids external
contractors from moving a case **to** *Avslutad* at all (and out of *Utförd*,
*Avslutad*, *Återsänd*). So a contractor can **decline** a close request but can
never **accept** one. The design therefore shows contractors only the *Avslå*
action; an accepted-in-principle request stays pending until a Mimer user closes
the case. No rule is loosened.

## Existing mechanics this builds on

- **"Meddelande från kund" is a computed flag, not a tag.** `last_customer_message_at`
  vs `customer_message_ack_at` on `maintenance.request` drive the stored
  `customer_message_unread` (first key of `_order`), a kanban badge, and a chatter
  acknowledge button (`action_acknowledge_customer_message`) that posts a
  `receipt_to_tenant` message. The close request copies this shape.
- **Message types** are a `selection_add` in `onecore_mail_extension/models/mail_message.py`,
  mirrored by hand in `onecore_maintenance_extension/models/constants.py`. Any
  type prefixed `tenant_` is dispatched as outbound SMS/e-mail by `create()`, so
  new types must not use that prefix. Every type must be listed in the log
  category test's `EXPECTED_CATEGORIES`.
- **Mina sidor only sees whitelisted types.** `MESSAGE_DOMAIN` in
  `onecore/services/work-order/.../odoo-adapter/index.ts` filters by
  `message_type`; anything else is invisible to the tenant even though every
  layer reports success (see `docs/end-to-end-flows.md` in the Mimer workspace).
- **Prior art for a new type across the chain:** MIM-1957
  (`onecore/docs/superpowers/specs/2026-08-26-mim-1957-mina-sidor-message-channel-design.md`).

## Design

### 1. Odoo (`onecore-odoo`)

**Message types** (`mail_message.py` `selection_add` + `constants.py`, category
Kommunikation, added to `EXPECTED_CATEGORIES`):

| Type | Written by | Body |
|---|---|---|
| `close_request_from_tenant` | integration, on the tenant's behalf | "Begäran om att avsluta ärendet" + the tenant's reason if given |
| `close_request_declined` | the deciding Odoo user | the required reason |

Bodies are neutral so the same text reads right in the chatter and on Mina sidor.

**Fields on `maintenance.request`:**

- `close_requested_at` — Datetime, set by the tenant entry point.
- `close_request_resolved_at` — Datetime, set on accept, decline or auto-resolve.
- `close_request_pending` — stored computed Boolean, `requested_at and (not resolved_at or requested_at > resolved_at)`.
- `_order` becomes `close_request_pending desc, customer_message_unread desc, recently_added_tenant desc, request_date desc`.

**Tenant entry point** — `request_close_from_tenant(reason=None)`, called over XML-RPC:

1. Raise a `UserError` with a stable code-like message if the case is *Avslutad*,
   `hidden_from_my_pages`, or already `close_request_pending`.
2. Post `close_request_from_tenant` (reason HTML-escaped, newlines → `<br>`; whitespace-only counts as no reason).
3. Set `close_requested_at = now`.

A dedicated method rather than a `message_post` override keeps the rules in one
place and gives the adapter a single thing to call.

**Staff actions:**

- `action_accept_close_request` — writes `stage_id` = *Avslutad* **as the current
  user**, so the normal workflow and contractor rules run. Resolution happens via
  auto-resolve below. Not offered to external contractors.
- `action_decline_close_request` — opens a transient wizard
  (`maintenance.close.request.decline.wizard`) with a required *Orsak* field. On
  confirm: post `close_request_declined`, set `close_request_resolved_at = now`.

**Auto-resolve:** `maintenance_workflow_service`, where it already stamps
`closed_date` on the transition to *Avslutad*, also sets
`close_request_resolved_at` if a request is pending. A request can never outlive
the case being closed.

**UI** (Swedish strings):

- New `.mimer-badge-purple` in `static/src/scss/mimer_styles.scss` (Material purple
  50 / 300 / 900: `#F3E5F5` / `#BA68C8` / `#4A148C`). Four badges are already
  orange ("unread, acknowledge"); this is the only badge that asks for a decision,
  so it gets its own colour, plus a `fa-flag-checkered` icon so colour is not the
  only signal.
- Badge "Hyresgäst vill avsluta" first in the badge column of
  `maintenance_request_item.xml` (the mobile card reuses this template), and beside
  the existing badges in the form.
- Chatter signal in the same purple, following the customer-message signal in
  `tenant_chatter_patch.js`, with buttons *Avsluta ärendet* (hidden for external
  contractors) and *Avslå*.

**Tests** (`TransactionCase`, `@tagged("onecore")`):

- request posts the message and sets pending; refused when pending, *Avslutad* or hidden
- accept closes and resolves; contractor cannot accept
- decline requires a reason, posts it, resolves; contractor can decline
- drag to *Avslutad* resolves a pending request
- a new request after a decline is pending again
- log categories for both new types

### 2. onecore (`services/work-order`, `libs/types`, `core`)

**work-order service**

- Odoo adapter: new `requestCloseWorkOrder(id, reason?)` calling
  `maintenance.request.request_close_from_tenant`. The three refusals map to a
  typed `CloseRequestConflictError`; anything else stays an error. The existing
  `closeWorkOrder` (a real stage change) stays: staff use it via property-tree's
  inspection flow.
- `MESSAGE_DOMAIN` gains `close_request_from_tenant` and `close_request_declined`.
- `WORK_ORDER_FIELDS` gains `close_request_pending`; `transformWorkOrder` maps it
  to `CloseRequestPending`.
- `messageAuthor` treats `close_request_from_tenant` like `from_tenant`.
- New route `POST /workOrders/:id/close-request`, body `{ reason?: string }`,
  returning 200 / 400 / 409 / 500. `POST /workOrders/:id/close` is unchanged.
- `CloseRequestPending` goes on the service's own work-order schema
  (`schemas.ts`), which reaches core through its Swagger and regenerated types.

**libs/types** — `CloseWorkOrderRequestSchema` (`{ reason?: string }`), shared by
the service and core routes. libs/types has no work-order Zod schema to extend.

**core**

- Regenerate `generated/api-types.ts` from the service's Swagger, then add
  adapter `requestCloseWorkOrder(id, reason?)` over `openapi-fetch`, mapping 409 to
  `'conflict'`.
- New route `POST /work-orders/:workOrderId/close-request` passing the outcome
  through (200 / 400 / 409 / 500). The staff `/close` route is unchanged.
- `closeRequestPending` in `CoreWorkOrderSchema` and every `CoreWorkOrder`
  mapping, including `GET /work-orders/by-contact-code`, which the API reads.

**Tests** — Jest for the adapter (domain, fields, refusal → conflict), the
work-order route (409 path) and the core route (status passthrough).

### 3. .NET API (`mimer-nu/API`)

- **Ownership check** in `CloseWorkOrderHandler` and `UpdateWorkOrderCommandHandler`:
  load the logged-in tenant's Odoo work orders by the contactCode from the token;
  if `"od-" + id` is not among them, fail before calling core. The controller
  returns 403. Today both endpoints act on any id. The lookup must distinguish
  "core failed" (502) from "not yours" (403), so it uses a variant of the list
  call that reports failure instead of returning an empty list. Admin/developer
  tokens, which have no contact code, lose the ability to act on arbitrary ids.
- **Error propagation:** both controllers return the handler result — 204 on
  success, 409 passed through, 502 when core fails. Today both always return 204.
- `CloseWorkOrderRequest` DTO with optional `Reason`. `OneCoreWorkOrderService`
  builds request bodies with a JSON serializer for both close and update instead
  of string concatenation.
- `WorkOrderResponse` gains `CloseRequestPending`.
- The endpoint URL `~/api/workorders/close/{id}` is unchanged. Behind it,
  `OneCoreWorkOrderService` now calls core `work-orders/{id}/close-request`.
- The API gains a test project (`tests/Api.Tests`, xunit + Moq); none exists today.

**Tests** — handler tests for foreign-id rejection, 409 passthrough and core
failure.

### 4. Mina sidor (`mimer-nu/Webbappar/mina-sidor`)

**Button** (`WorkorderList.vue`)

- `workOrderCanBeClosed`: code starts with `od-` and status is not *Avslutad*.
  Xpand cases stay excluded.
- Label unchanged: "Jag vill avsluta ärendet".
- When `closeRequestPending` is true: disabled, text "Begäran om avslut skickad – väntar på svar".

**Dialog**

- Copy says the request goes to whoever handles the case and the answer arrives
  in the thread — not that the case will be closed.
- Optional reason, reusing `UpdateWorkOrderTextArea` (500 characters).
- On success, refetch work orders instead of `window.location.reload()`.
- 409 → "Det finns redan en begäran som väntar på svar"; other errors → the
  standard error text.

**Thread**

- `close_request_from_tenant` renders as the tenant ("Du", orange avatar) with a
  small "Begäran om avslut" label.
- `close_request_declined` renders as staff with an "Avslutsbegäran avböjd" label.
- `workorders.js`: `fromTenant` includes `close_request_from_tenant`.

**Update path** — the `JSON.stringify(msg).slice(1, -1)` workaround goes away
once the API serializes bodies properly.

## Error handling summary

| Situation | Odoo | work-order | core | API | Mina sidor |
|---|---|---|---|---|---|
| Already pending / closed / hidden | `UserError` | 409 | 409 | 409 | "redan en begäran…" |
| Foreign work order | — | — | — | 403, core not called | standard error |
| Odoo/core down | — | 500 | 500 | 502 | standard error, button stays enabled |
| Contractor clicks *Avslå* without reason | wizard validation | — | — | — | — |

## Release order

onecore-odoo first (new method and fields must exist before work-order reads
`close_request_pending` or calls `request_close_from_tenant`), then onecore, then
**API and Webbappar back to back**: once the API serializes the update body
properly, today's Mina sidor pre-escaping would store literal `\n` and `\"`, and
Mina sidor without its hack against today's API sends broken JSON. Odoo follows the standard three steps: `odoo-git-install`,
`odoo-module-upgrade`, then restart.

## Verification

1. Unit tests in each repo, as listed per section.
2. Local end-to-end (the workspace `local-e2e` skill) on the real stack with Xpand
   test data: request → button disabled → decline with reason shown on Mina sidor
   → button enabled → request again → accept → *Avslutad*; a foreign work-order
   id is rejected; a contractor sees only *Avslå*.
3. Epic environment `epic-mim-1983` (the `epic-e2e` skill) before MIM-2036 is
   moved to Ready for Test.

## Amendments from planning

Found while drafting the plan against the real code:

- **Staff also call `/close`.** property-tree closes stale inspection work orders
  through core `POST /work-orders/{id}/close`. Decision: that route keeps meaning a
  real close; the tenant request gets its own `/close-request` route in
  work-order and core.
- **Tenant-facing sender (MIM-2040).** `close_request_declined` is a
  tenant-facing type and stores the deciding user's sender label, so a
  contractor's decline reads "Mimers Leverantör - <resursgrupp>" rather than
  "Mimer". `close_request_from_tenant` stores none.
- **Row lock.** Odoo 19's `lock_for_update()` uses `SKIP LOCKED` and raises
  without the conflict prefix; a plain `SELECT … FOR UPDATE` is used so the
  losing concurrent call ends as `already_pending`.
- **Second resolution.** Datetimes are second-precision, so a request in the same
  second as a decline sets `close_requested_at` one second after
  `close_request_resolved_at`.
- **Field-change notes.** The two timestamps are added to
  `FieldChangeTracker.SKIP_FIELDS` so stamping them posts no chatter note.
- **Mina sidor's axios interceptor** swallows 401/403/404/409; the close and
  update calls read the status themselves. The page's single dialog state becomes
  per work order, which also fixes text typed on one card being sent from another.
- **Known, not fixed here:** the existing core `closeWorkOrder` adapter reads a
  `content` wrapper the service never sends; closed cases show no thread on Mina
  sidor.

## Out of scope

- Xpand-handled work orders (no close request possible).
- Notifying the tenant by SMS or e-mail about the decision.
- Changing contractor stage permissions.
