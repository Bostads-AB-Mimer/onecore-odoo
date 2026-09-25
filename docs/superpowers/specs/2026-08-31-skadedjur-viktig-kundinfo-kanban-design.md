# Design: Skadedjur & viktig kundinfo i kanbanvyn (MIM-1959)

**Ticket:** [MIM-1959](https://linear.app/mimer-onecore/issue/MIM-1959/visa-skadedjur-and-viktig-kundinfo-i-kanbanvyn-och-pa-arendet)
**Parent epic:** MIM-1983
**Branches:** `feature/mim-1959-visa-skadedjur-viktig-kundinfo` (onecore-odoo, off
`epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`) ·
`feature/mim-1959-rental-blocks-rental-ids` (onecore, off `epic/mim-1983`)
**Date:** 2026-08-31

## Problem

The ticket asks for two safety badges to be visible both in the kanban overview
and on the case itself, and notes that a skadedjursspärr added *after* the case
was created must still reach the case. It also asks, about the lookups this
implies: *"blir många slagningar, kan vi göra batch?"*

The current state is asymmetric:

- **Viktig kundinfo** already renders in the kanban card
  (`static/src/views/maintenance_request_item.xml:14`), on the form
  (`views/maintenance_views.xml:172`) and in the list
  (`views/maintenance_views.xml:996`). It is
  `maintenance.tenant.special_attention`, snapshotted from OneCore's tenant
  payload when the case is created (`models/handlers/base_handler.py:124`) and
  **never refreshed**. A flag set in Xpand after case creation never arrives.
- **Spärr skadedjur** renders only on the form
  (`views/maintenance_views.xml:177`). It is `requires_pest_control`, a
  non-stored compute doing a live `fetch_residence` per record with a 5-minute
  per-worker cache (`models/maintenance.py:44-47, 205-209, 414-451`). Its own
  comment states why it is form-only: *"Adding this to tree/kanban would fire
  one API call per row."*

So the gap is: the pest badge cannot reach the kanban while it is computed
per-record, and neither flag is refreshed after creation.

A second, quieter defect: because the compute only ever calls
`fetch_residence`, cases on a parking space or a facility silently resolve to
`False` — the 404 is swallowed by the `except` at `models/maintenance.py:446`.

## Decisions

Confirmed with the assignee during brainstorming:

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Scope is exactly the **two** badges — Viktig kundinfo and Spärr skadedjur | "Dom olika symbolerna" in the ticket means this pair, which already sit side by side on the form. No further OneCore flags, no promotion of Husdjur/Hörselnedsättning to badges |
| 2 | **Stored value everywhere.** Form and kanban read the same synced field; the live compute and its cache are deleted | One code path, zero HTTP on any read path (the MIM-1869 rule), badge at most one cron interval stale |
| 3 | **Silent update.** A flag flipping by sync changes the badge and nothing else — no chatter note, no unread marker | Satisfies the ticket literally; the kanban overview is where a handläggare would spot it. Avoids new ack machinery and noise if a block flaps |
| 4 | **New lean endpoint in onecore** for the pest set, rather than reusing `/residences/rental-blocks/search` | See "Why not the search endpoint" below |
| 5 | Parking and facility cases get the badge too | Not a requirement — the assignee's position is "only residence really needs it, other types having it is not an issue". It falls out of the batch design at no cost, and is more correct than today's silent `False` |
| 6 | **No per-record sync timestamp**; only records whose value actually changed are written | See "Why no timestamp" below |

## Why not the search endpoint

`/residences/rental-blocks/search?blockReason=SKADEDJUR&active=true` exists and
is already proxied by core
(`core/src/services/property-base-service/index.ts:1484`), so it was the
obvious candidate and needs no onecore change. It was rejected after reading
what it does per page (`services/property/src/adapters/residence-adapter.ts:1493`):

- a `COUNT` query, plus a `findMany` with a wide include (`rentalBlockInclude`
  at `:1453` — residence type, building, property, administrative unit)
- `fetchRentDataBatched()` for every rental id on the page
- `fetchDistrictsByFencode()` for every row missing a district

It is built to power the spärrlista list UI, and all of that enrichment would
be fetched and discarded to keep one boolean per rental id. It also needs
paging.

Cross-checking how property-tree's residence view answers the same question
confirmed the endpoint is not the established path for it
(`apps/property-tree/src/features/residences/ui/ResidenceBasicInfo.tsx:48`):

```ts
const hasPestIssues = residence?.propertyObject?.rentalBlocks?.find(
  (b) => b.blockReason === 'SKADEDJUR'
)
```

It reads the blocks embedded in the residence payload — the same
`/residences/by-rental-id/{rentalId}` call Odoo makes today — one object at a
time. Nobody batches this question yet, which is precisely what the ticket
asks for.

That check did settle one assumption in our favour: `blockReason` is
`blockReason.caption` on every path (`services/property/src/routes/residences.ts:466`,
and the search filter is `blockReason: { caption: { in: [...] } }`), and
comparing against the literal `'SKADEDJUR'` is the established convention in
both repos.

## onecore: the lean endpoint

**`GET /residences/rental-blocks/rental-ids`** in the property service
(`services/property/src/routes/residences.ts`), proxied by core
(`core/src/services/property-base-service/index.ts`).

Query params: `blockReason` (repeatable, same caption semantics as the search
endpoint), `active` (boolean, same semantics: `toDate >= today or null`).

Response: `{ content: string[] }` — distinct, trimmed rental ids, no paging.

Implementation reuses `buildRentalBlockWhereClause()`
(`residence-adapter.ts:1137`) so the filter semantics cannot drift from the
spärrlista, but selects only `propertyStructure.rentalId` and does no COUNT, no
rent lookup and no district enrichment. The clause's existing base filter
(`propertyStructure.rentalId != ''`) already guarantees every row has one.

Note the endpoint is deliberately *not* SKADEDJUR-specific — a generic
`blockReason` filter is the same amount of code and keeps the route reusable.

## Odoo: data model

**`maintenance.request.requires_pest_control`** — flips from non-stored compute
to `store=True, readonly=True`, written only by the sync service. Delete
`_compute_requires_pest_control`, `PEST_CONTROL_CACHE_TTL` and
`_pest_control_cache`.

**`maintenance.tenant.special_attention`** — unchanged in shape. Already stored,
already related onto the request through `TenantFieldsMixin`. The sync starts
refreshing it in place.

No new fields.

### Why no timestamp

`ManagementAreaService` carries `management_area_lookup_at` because it *stamps
records to exclude them from future runs* — its cost scales with how many
records still need work.

This sync is different: every run rebuilds the answer for every open case from
one global map, so there is nothing to exclude. A per-record stamp would mean a
full-table `UPDATE` every 15 minutes and would destroy the property that makes
this cheap: **only records whose value actually changed are written.** Steady
state is zero writes. Observability comes from a run summary in the log, the
same way `backfill_batch` logs its counts.

## Odoo: the sync service

New `models/services/onecore_flag_sync_service.py` → `OneCoreFlagSyncService`,
following the shape of `ManagementAreaService`.

```
                    ┌─────────────────────────────────────┐
   cron 15 min ────>│ sync_pest_control()                 │
                    │  1 call: /rental-blocks/rental-ids  │──> set[rental_id]
                    │  → 2 grouped writes (changed only)  │
                    └─────────────────────────────────────┘
                    ┌─────────────────────────────────────┐
   cron 1 h    ────>│ sync_special_attention()            │
                    │  ⌈codes/200⌉ calls: /v1/contacts/   │──> {code: bool}
                    │    batch                            │
                    │  → 2 grouped writes (changed only)  │
                    └─────────────────────────────────────┘
```

- `is_configured()` — guards on `onecore_base_url` *before* constructing
  `CoreApi`, whose `__init__` POSTs for a token when none is persisted. Same
  guard as `ManagementAreaService.is_configured()`.
- `fetch_pest_blocked_rental_ids(api)` → `set[str]`. **Raises** on failure. A
  partial or empty-by-accident set would clear the flag on genuinely blocked
  objects, so this is all-or-nothing, exactly like `build_property_map()`.
- `sync_pest_control()` — searches
  `[("closed_date", "=", False), ("active", "=", True)]`, resolves each
  request's rental id, then issues at most two writes: the ids that must become
  `True`, and the ids that must become `False`.
- `fetch_special_attention(codes, api)` → `dict[code, bool]`, chunking codes
  ~200 per call. A code **absent** from a response means *unknown*, not
  `False`; those records are left alone.
- `sync_special_attention()` — distinct `contact_code` over `maintenance.tenant`
  rows whose request is open, then grouped writes on change only.

### Resolving a request's rental id

All three object models carry `rental_property_id` (OneCore's rentalId) as a
`Char`: `maintenance.rental.property:42`, `maintenance.parking.space:31`,
`maintenance.facility:31`. The service resolves it in this order, and stops at
the first hit:

1. `request.rental_property_id.rental_property_id` (residence)
2. `request.parking_space_id.rental_property_id` (parking)
3. `request.facility_id.rental_property_id` (facility)

A request with none of the three (a property- or building-level case) has no
rental object to block and is skipped — it can never be `True`, and must be
written to `False` if it somehow holds a stale `True`.

Note this drops the `rental_property_option_id` fallback the old compute used
(`models/maintenance.py:420`). Options are transient pre-save search records;
the sync only ever runs against saved requests, where the snapshot exists.

### Guard against a caption rename

The pest filter matches on a caption, and an empty result set is
indistinguishable from "nothing is blocked" — so a rename in Xpand would make
the sync clear the flag on every case. Silent, and the wrong direction for a
safety badge.

`sync_pest_control()` therefore calls `/residences/block-reasons` (lookup data,
proxied by core at `core/src/services/property-base-service/index.ts:1659`,
cacheable) and **aborts the run with a loud log** if `SKADEDJUR` is not among
the captions, rather than writing `False` everywhere.

### Reading specialAttention

`GET /v1/contacts/batch?code=P1&code=P2…`
(`core/src/api/v1/contacts/index.ts:130`) is already the lean path — its
repository method is documented as selecting only base `cmctc` columns with no
row explosion (`services/contacts/src/adapters/xpand/batch-query.ts:53-60`). No
onecore change needed.

Read `content[].contactCode` and `content[].communication.specialAttention`.
Note that this endpoint returns the untransformed domain contact while
declaring the transformed schema (unlike `/v1/contacts`, which calls
`transformContacts` at `:122`). The difference is confined to
`personal.nationalId` vs `nationalRegistrationNumber` and `careOf` handling —
`communication.specialAttention` is identical either way, so the sync is
unaffected. Worth a separate ticket, not this one.

Two new `CoreApi` methods in `onecore_api/core_api.py`:
`fetch_pest_blocked_rental_ids(...)` and `fetch_contacts_batch(codes)`. The
latter builds its query string with `urlencode(..., doseq=True)`.

## Odoo: scheduling

Two crons in `data/ir_cron.xml`, `noupdate="1"`, pinned to `base.user_root`,
following the existing file's stated reasoning (*"Two jobs on purpose: they have
completely different tempos"*):

| Cron | Interval | Cost per run |
|---|---|---|
| Skadedjursspärr | 15 min | 1 call, flat, regardless of case volume |
| Viktig kundinfo | 1 hour | ⌈distinct open contact codes / 200⌉ calls |

`specialAttention` is a hand-set flag in Xpand that changes very rarely, so it
does not earn a 15-minute cadence at roughly a dozen calls per run.

Each sync is wrapped so that one failing does not prevent the other.

## Odoo: new cases do not wait for the cron

`create()` populates the pest flag immediately, off a per-worker TTL-cached copy
of the blocked-rental-id set — the same mechanism as `_district_cache` in
`ManagementAreaService`. The first create after TTL expiry pays one call; the
rest are free.

This is the *write* path, which the MIM-1869 rule permits and where
`ManagementAreaService.populate()` already does a lookup. Without it, a case
opened on a flat with an active pest block shows no warning for up to 15
minutes — the one window where the badge actually protects the person going
there.

A failure here is swallowed and logged, never raised: OneCore being unreachable
must not stop a handläggare (or an inbound mimer.nu request) from creating a
case. The flag stays `False` and the next cron run heals it. This is the one
place `fetch_pest_blocked_rental_ids` is called without its all-or-nothing
contract mattering, because a create writes one record rather than clearing a
whole table.

`special_attention` already snapshots at create from the tenant payload
(`base_handler.py:124`); unchanged.

## Odoo: views

- **Kanban** — add `<field name="requires_pest_control" />` to the field list
  (`views/maintenance_views.xml:946`, next to `special_attention`), and a badge
  in `static/src/views/maintenance_request_item.xml` directly after the "Viktig
  kundinfo" one. Same colours as the form badge (`bg-warning text-dark`) so the
  two views read identically.
- **Form** — no change. The badge already exists
  (`views/maintenance_views.xml:176-181`); it starts reading a stored value
  instead of computing one.
- **List** — add `<field name="requires_pest_control" optional="hide" />`
  alongside `special_attention` (`views/maintenance_views.xml:996`), plus a
  "Spärr skadedjur" search filter. Now that the field is stored it can be
  filtered and grouped, which is the natural way to answer "which of my cases
  are blocked".
- **Mobile** — `views/mobile_view.xml:51` already lists `special_attention`; add
  the pest field and badge so the kvartersvärd in the field sees the same
  warning.

## Testing

New `tests/models/services/test_onecore_flag_sync_service.py`, `@tagged("onecore")`,
`CoreApi` patched as elsewhere in the suite:

**Pest**
- a blocked rental id sets the flag; a lifted block clears it
- parking and facility rental ids resolve (regression cover for today's silent `False`)
- a failed fetch writes nothing and an existing `True` survives
- `SKADEDJUR` missing from `/residences/block-reasons` aborts the run without clearing
- closed (`closed_date` set) and archived (`active = False`) cases are excluded
- a run where nothing changed issues no writes

**Viktig kundinfo**
- chunking splits at the boundary and merges results
- a code missing from the response leaves the stored value untouched
- a changed value is written

**Create path**
- a new case on a blocked rental id gets the flag without a cron run

`tests/models/test_maintenance_pest_control.py` currently tests the compute and
cache this design deletes. Rewrite rather than drop it — the
SKADEDJUR-vs-other-blockReason semantics it pins down are still the behaviour we
care about, just at the service level.

**onecore** — route tests for the new endpoint alongside the existing rental-block
route tests: filter by `blockReason`, `active` semantics, distinct ids, empty
result.

## Rollout

Adding `store=True` to an existing non-stored field makes Odoo create the column
defaulted to `False`, and since the compute is gone there is no recompute pass.
Existing open cases therefore show no pest badge until the first cron run — at
most 15 minutes after deploy. No SQL migration.

The onecore endpoint must be deployed before the Odoo cron goes live. Until it
is, `fetch_pest_blocked_rental_ids` raises, the sync aborts, and no flags are
written — which is the safe failure direction.
