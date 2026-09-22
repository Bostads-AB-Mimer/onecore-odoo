# Design: Förändrad prioritet-mekanism i ärende-vyn (MIM-2038)

**Ticket:** [MIM-2038](https://linear.app/mimer-onecore/issue/MIM-2038/forandrad-prioritet-mekanism-i-arende-vyn)
**Branch:** `feature/mim-2038-forandrad-prioritet-mekanism-i-arende-vyn`
**Base / PR target:** `epic/mim-1983-epic-odoo-prioritized-ux-and-communication-improvements`
**Date:** 2026-09-22
**Status:** design sketch — several decisions below are still open to verksamheten

## Problem

Prioritet on a maintenance request is a 13-entry dropdown running from *Akut*
to *mer än 1 år*. Verksamheten wants to keep the short end (*Akut* … *7 dagar*)
as fixed choices, and replace the long tail — *2, 3, 4, 5, 6, 8 veckor,
6 månader, mer än 1 år* — with a **"Välj antal veckor"** option where the
handläggare types the number themselves.

The change looks like a dropdown edit and is not, because of one fact:

> `priority_expanded` is not a label. **Its value is the arithmetic.**
> `due_date = base_date + int(priority_expanded)`
> (`onecore_maintenance_extension/models/maintenance.py:844`)

The stored value and the rendered label are the same string. That single
conflation is what produces all three of the symptoms this ticket touches:

1. **No free entry** — a value that is not in the Selection list cannot be stored.
2. **One quick-filter per literal value** — 11 hardcoded filters in the search
   view, one per option, which stop being writable the moment the value is free.
3. **Prioritet sorts wrong** — the column is `varchar`, so the list orders
   `0, 1, 10, 14, 183, 21, 28, 35, 42, 5, 56, 7, 365`. Not in the ticket, but
   fixed for free by the design below.

## Current state, verified

| Thing | Where | Note |
|---|---|---|
| `PRIORITY_OPTIONS` (13 tuples, value = days) | `models/constants.py:54` | `"0"` Akut … `"365"` mer än 1 år |
| `priority_expanded = fields.Selection(...)` | `models/maintenance.py:115` | stored, nullable |
| `due_date` stored compute + inverse | `models/maintenance.py:120,844,854` | inverse exists so a manually typed date sticks |
| Stage gate: priority must be set | `models/services/maintenance_workflow_service.py:100` | `not record.priority_expanded`; exempt stages: Väntar på handläggning, Avslutad, Återsänd |
| 11 quick-filters, one per value | `views/maintenance_views.xml:46-67` | `183`/`365` have no filter |
| Form: read-only display block | `views/maintenance_views.xml:232` | |
| Form: editable field | `views/maintenance_views.xml:779` | |
| Kanban + list + mobile field loads | `views/maintenance_views.xml:975,1046`, `views/mobile_view.xml:36` | not rendered in any OWL template |
| 7 test files | `tests/` | `tests/utils/test_utils.py:147` seeds `"7"` |

### Cross-repo: one write, no reads

`onecore/services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts:715`
writes `priority_expanded: '7'` over XML-RPC when creating a besiktning
request. That is the **only** reference to `priority_expanded` anywhere outside
this repo — nothing reads it.

The `priority` that work-order *does* read (`WORK_ORDER_FIELDS`, surfaced to
Mina sidor as `Priority` via `odoo-adapter/utils.ts:78`) is Odoo's **stock**
`maintenance.request.priority` star field. This addon never declares or
overrides it, so it is untouched by this change.

**Consequence for the design:** if `priority_expanded` keeps its name, its type
and `'7'` as a valid value, this ticket requires **no onecore change and no
co-release at all**. The design below is built to hold that property.

## Approach

Separate the two things the field currently conflates:

- **`priority_expanded` stays the picker** — same name, same `Selection` type,
  same nullability. Presets shrink to Akut / 1 dag / 5 dagar / 7 dagar /
  10 dagar, plus one new sentinel `custom` = *"Välj antal veckor"*.
- **`priority_days` becomes the arithmetic** — a new stored `Integer`, derived,
  and the single thing `due_date`, sorting, filtering and grouping read.

Two approaches were considered and rejected:

- *Replace `priority_expanded` with an Integer outright.* Cleanest data model,
  but breaks the work-order write and forces a coordinated two-repo release for
  no user-visible gain.
- *Drop priority entirely and let handläggare set Förfallodatum directly.*
  Nearly free — `due_date` already has an inverse, so a typed date sticks
  today. Rejected as a unilateral technical decision: priority gates stage
  transitions and is shown to external contractors. Worth putting to
  verksamheten as the cheap alternative (see Open questions).

### The trap this design exists to avoid

An `Integer` cannot distinguish *unset* from *Akut*. Odoo's `fields.Integer`
converts `False` and SQL `NULL` to `0` on read, and **Akut is 0 days**. So
this, with `priority_days` as the only field, is a production bug:

```python
return not record.priority_expanded   # maintenance_workflow_service.py:105
```

Every Akut ärende would read as "priority not set" and be blocked from moving
to a handling stage. Keeping the nullable `Selection` as the picker means the
set/unset question is still answered by a nullable column, and
`maintenance_workflow_service.py` needs **no change at all**.

**And it applies to `priority_days` itself.** An earlier draft of this design
proposed writing `priority_days = False` so that unset ärenden would be SQL
`NULL` and not collide with Akut. That is not possible:

```python
# odoo/orm/fields_numeric.py:32
def convert_to_column(self, value, record, values=None, validate=True):
    return int(value or 0)
```

`fields.Integer` has `falsy_value = 0` and coerces `False` to `0` on the way
into the column. There is no nullable integer in the Odoo ORM. So
`priority_days` **is `0` for an unset ärende and `0` for Akut**, and cannot
distinguish them — which is fine, because it is never asked to:

> **`priority_days` answers "how many days". `priority_expanded` answers
> "is a priority set". Never the other way round.**

Every filter, every `invisible=`, and the stage gate go through
`priority_expanded`, which is a nullable `Selection` and does distinguish the
two. `priority_days` is used only for the arithmetic, for sorting and for
grouping.

`priority_label` is the one derived field that *is* nullable — `Char` stores
`NULL` happily — so it is computed as `False` when `priority_expanded` is
unset rather than rendering "Akut" on an unprioritised ärende.

## Model

```python
# constants.py
PRIORITY_CUSTOM = "custom"

PRIORITY_PRESETS = [
    ("0", "Akut"),
    ("1", "1 dag"),
    ("5", "5 dagar"),
    ("7", "7 dagar"),
    ("10", "10 dagar"),
    (PRIORITY_CUSTOM, "Välj antal veckor"),
]

PRIORITY_MAX_WEEKS = 52
```

```python
# maintenance.py
priority_expanded = fields.Selection(
    PRIORITY_PRESETS, string="Prioritet", store=True,
)
priority_weeks = fields.Integer(
    "Antal veckor", store=True,
)
priority_days = fields.Integer(
    "Prioritet (dagar)", compute="_compute_priority_days",
    store=True, readonly=True,
)
priority_label = fields.Char(
    "Prioritet", compute="_compute_priority_label", store=True, readonly=True,
)
```

`_compute_priority_days` — depends on `priority_expanded`, `priority_weeks`:

| `priority_expanded` | `priority_days` |
|---|---|
| unset | `0` (meaningless; nothing reads it without checking `priority_expanded` first) |
| `custom` | `7 * priority_weeks`, or `0` if weeks is unset |
| anything else | `int(priority_expanded)` |

`_compute_priority_label` — the one place that turns a day count back into
Swedish, so list, kanban, mobile and the contractor-facing read-only block all
agree. It is also the nullable witness for "has a priority at all":

| Condition | Label |
|---|---|
| `priority_expanded` unset | `False` |
| `priority_days == 0` | `"Akut"` |
| `priority_days % 7 == 0 and priority_days >= 14` | `"{n} veckor"` |
| `priority_days == 1` | `"1 dag"` |
| otherwise | `"{n} dagar"` |

`_compute_due_date` changes only its day source — `int(record.priority_expanded)`
becomes `record.priority_days` — and keeps its existing
`if base_date and record.priority_expanded:` guard verbatim. That guard is
already correct for Akut, because `priority_expanded` is the non-empty string
`"0"` there, which is truthy in Python. Its `@api.depends` gains
`priority_days`. The existing `_inverse_due_date` no-op stays — it is what lets
a manually typed förfallodatum survive a flush, and that behaviour must not
change.

A `@api.constrains("priority_expanded", "priority_weeks")` rejects
`custom` with weeks outside `1..PRIORITY_MAX_WEEKS`, in Swedish.

## Views

**Form, editable (`maintenance_views.xml:779`)** — `priority_expanded`
unchanged, followed by `priority_weeks` with
`invisible="priority_expanded != 'custom'"` and
`required="priority_expanded == 'custom'"`, inheriting the same
`readonly="user_is_external_contractor"`.

**Form, read-only block (`:232`)** — swap `priority_expanded` for
`priority_label`, so a custom priority reads "9 veckor" rather than the raw
sentinel. `invisible="not priority_label"`.

**List (`:1046`), kanban (`:975`), mobile (`views/mobile_view.xml:36`)** —
show `priority_label`; additionally load `priority_days` in the list so the
Prioritet column can be made sortable in a follow-up. `priority_label` is a
stored `Char`, so it would sort alphabetically — **sort on `priority_days`, not
on the label.** Making the visible column sort numerically while showing the
label needs a small OWL field widget (the repo already has the
`*_field_*.js` pattern); that is deliberately **out of scope** here and noted
under Follow-ups.

**Quick-filters (`:46-67`)** — the 11 per-value filters cannot survive a free
value. Replace with four ranges plus a group-by:

```xml
<filter string="Akut"              name="priority_acute"   domain="[('priority_expanded', '=', '0')]" />
<filter string="Inom 7 dagar"      name="priority_week"    domain="[('priority_expanded', '!=', False), ('priority_days', '&gt;', 0), ('priority_days', '&lt;=', 7)]" />
<filter string="8–30 dagar"        name="priority_month"   domain="[('priority_expanded', '!=', False), ('priority_days', '&gt;', 7), ('priority_days', '&lt;=', 30)]" />
<filter string="Längre än 30 dagar" name="priority_long"   domain="[('priority_expanded', '!=', False), ('priority_days', '&gt;', 30)]" />
```

plus `<filter string="Prioritet" name="group_priority" context="{'group_by': 'priority_days'}" />`
in the group-by section, which now orders numerically because the column is an
integer.

**Every one of these leads with `priority_expanded`, not `priority_days`** —
that is the rule from the previous section applied. The Akut filter keeps the
form it already has today (`priority_expanded = '0'`), and the three ranges
carry `('priority_expanded', '!=', False)` so an unprioritised ärende, whose
`priority_days` is an incidental `0`, matches none of them.

The group-by is the one place the `0` collision is visible: an unprioritised
ärende groups together with Akut. Accepted — an ärende with no priority cannot
reach a handling stage anyway (the stage gate), so the boards where grouping is
used contain few of them. Switching the group-by to `priority_label` gives each
its own bucket at the cost of alphabetical ordering, and is a one-line change if
the collision turns out to matter in practice.

## Migration — `migrations/19.0.1.0.12/`

Manifest bumps `19.0.1.0.11` → `19.0.1.0.12`.

Every legacy value is already a day count, so the mapping is mechanical:

| Legacy `priority_expanded` | New `priority_expanded` | `priority_weeks` |
|---|---|---|
| `0`, `1`, `5`, `7`, `10` | unchanged | — |
| `14`, `21`, `28`, `35`, `42`, `56` | `custom` | `2`, `3`, `4`, `5`, `6`, `8` |
| `183` (6 månader) | `custom` | `26` |
| `365` (mer än 1 år) | `custom` | `52` |
| `NULL` | `NULL` | — |

Odoo runs, in order: every applicable **pre-migration**, then `init_models()`
(which creates any column the current field definitions declare and fills
newly-added stored computes for every existing row), then every applicable
**post-migration** — the ordering spelled out in
`migrations/19.0.1.0.7/pre-migration.py`. That ordering dictates the split.

**`pre-migration.py`** — must run before `init_models()`, because Odoo
validates Selection values against the current field definition and `14`…`365`
are about to stop being declared.

1. `ALTER TABLE maintenance_request ADD COLUMN IF NOT EXISTS priority_weeks integer`.
   Creating the column by hand here is **required, not an optimisation**:
   `init_models()` has not run yet, so the column does not otherwise exist, and
   step 3 has nowhere to write.
2. Capture every row's current `due_date` into a temporary column
   `_mim2038_due_date_backup`.
3. Rewrite `priority_expanded` and populate `priority_weeks` per the mapping
   table, in one guarded `UPDATE`.

`init_models()` then creates `priority_days` and `priority_label` as new stored
compute columns and fills them for every row, reading the values step 3 just
wrote — the same mechanism `migrations/19.0.1.0.10/post-migration.py` documents
for `lease_status_label`.

**`post-migration.py`**

4. Restore `due_date` from the backup wherever it differs, then drop the
   temporary column.
5. `invalidate_all()`, following the precedent in
   `migrations/19.0.1.0.10/post-migration.py` — steps 2-4 all write via raw SQL.

**Why steps 2/4 exist, and the uncertainty in them.** Raw SQL does not retrigger
an existing stored compute, so the `priority_expanded` rewrite alone would leave
`due_date` untouched. But `priority_days` is a *new* stored compute that
`init_models()` fills through the ORM, and `due_date` `@api.depends` on it — so
that fill plausibly marks `due_date` dirty and recomputes it. **This has not
been verified**, and the two outcomes differ on real data: for
`183 → 26 veckor (182 dagar)` and `365 → 52 veckor (364 dagar)` a recompute
silently moves an ärende's deadline by a day, and for any ärende with a
hand-typed förfallodatum it would overwrite it — precisely what
`_inverse_due_date` exists to prevent during normal operation.

Backing the column up and restoring it makes the outcome **deterministic either
way**: no ärende's förfallodatum changes, whichever way the recompute question
resolves. That is worth two cheap SQL statements rather than a bet.

Idempotent throughout: every `UPDATE` is guarded (`WHERE priority_expanded IN
(...)`, `IS DISTINCT FROM`), both added columns use `IF NOT EXISTS`, and the
backup column is dropped only after the restore.

## Files touched

| File | Change |
|---|---|
| `models/constants.py` | `PRIORITY_OPTIONS` → `PRIORITY_PRESETS`, `PRIORITY_CUSTOM`, `PRIORITY_MAX_WEEKS` |
| `models/maintenance.py` | 3 new fields, 2 new computes, `_compute_due_date` reads `priority_days`, 1 constraint |
| `views/maintenance_views.xml` | filters, group-by, form ×2, list, kanban |
| `views/mobile_view.xml` | `priority_label` |
| `migrations/19.0.1.0.12/pre-migration.py` | value remap + due_date backup |
| `migrations/19.0.1.0.12/post-migration.py` | due_date restore + cleanup |
| `__manifest__.py` | version bump |
| `i18n/sv.po` | new strings |
| `tests/` (7 files) | see below |

**Unchanged on purpose:**

- `models/services/maintenance_workflow_service.py` — the stage gate still
  reads `not record.priority_expanded`, still correct, still nullable.
- `static/src/js/schedule_date_validation.js` — only a docstring mentions
  `priority_expanded`. A `priority_weeks` edit reaches `due_date` through the
  same onchange result path the docstring already describes, so the
  "don't prompt on a recomputed due_date" behaviour holds. Worth updating the
  comment to say *priority* rather than `priority_expanded`.
- `onecore/services/work-order` — `priority_expanded: '7'` remains valid.

## Testing

All Python, `@tagged("onecore")` on `TransactionCase`, run via `./run_tests.sh`.

**`tests/models/test_priority.py`** (new)

- `priority_days` for each preset; `custom` + weeks → `7 * weeks`.
- Unset priority → `priority_days` is falsy **and** does not match the Akut
  filter domain. This is the regression test for the 0-vs-NULL trap.
- `priority_label` for: Akut, 1 dag, 10 dagar, 3 veckor, and a legacy 183.
- Constraint rejects `custom` with 0, negative and >52 weeks.
- Stage gate: an Akut request (`priority_days == 0`) moves to a handling stage
  without raising. This is the second half of the 0-vs-NULL regression test,
  and the one most likely to catch a careless later refactor.

**`tests/models/test_maintenance.py`** (existing) — the due-date cases at
`:78/:86/:94/:107` currently pass `"183"`, `"365"`, `"42"`, `"14"`. Rewrite as
`priority_expanded="custom", priority_weeks=26/52/6/2`. Keep at least one case
asserting that a manually written `due_date` still survives a later priority
change (`:118`).

**`tests/migrations/test_priority_migration.py`** (new) — exercise the mapping
table and, critically, assert `due_date` is byte-identical before and after for
a row that starts at `183`. Check whether the repo has an existing pattern for
testing migrations; if not, extract the mapping into a pure function in
`constants.py` and unit-test that, with the SQL verified by hand on a restored
copy (see Verification).

**`tests/utils/test_utils.py:147`** seeds `"7"` — still valid, no change.

## Open questions for verksamheten

Each is built so the answer is a one-line change.

| # | Question | Recommended default |
|---|---|---|
| 1 | Keep **"10 dagar"** as a preset? | Keep — one tuple in `PRIORITY_PRESETS`. |
| 2 | **6 månader / mer än 1 år** — own presets, or just "26/52 veckor"? | Fold into weeks. Nothing is lost; förfallodatum is preserved exactly by the migration. |
| 3 | **Min/max** on antal veckor? | `1–52`. |
| 4 | The **11 quick-filters** → four ranges + group-by? | As specified above. Ranges are a guess at how the boards are actually used — worth confirming against how the filters get used today. |
| 5 | Could prioritet be dropped entirely in favour of typing **Förfallodatum**? | No — but it is nearly free if they want it, and it is the honest cheap alternative to put on the table. |

Answers to 1–3 change `constants.py` only. Answer to 4 changes the search view
only. A *yes* to 5 replaces this whole design.

## Risks and known limitations

- **The 0-vs-NULL trap** is the highest-risk part of this change and the reason
  the picker stays a nullable `Selection`. Any future refactor that collapses
  `priority_expanded` into `priority_days` reintroduces it. The two regression
  tests above exist to make that failure loud.
- **`due_date` recompute during upgrade.** Handled by the backup/restore pair,
  but it is the step most worth checking on a restored production copy before
  release — a mistake here moves real deadlines on real ärenden. Whether
  `init_models()` actually triggers the recompute is an open question (see
  Migration); the backup makes the answer not matter, it does not answer it.
- **Prioritet column sorting** improves (numeric `priority_days` exists) but the
  *visible* column shows `priority_label`, which sorts alphabetically. Until the
  follow-up widget lands, the sortable column and the pretty column are not the
  same column.
- **Historical labels drift.** A request migrated from "6 månader" now reads
  "26 veckor". The förfallodatum is unchanged, but the wording in an old ärende
  changes retroactively. Cheap to avoid (keep exact days) if verksamheten
  objects — see open question 2.

## Verification still needed

Nothing below has been run yet; this is a design, not a verified
implementation.

- Confirm how large the `priority_days == 0` collision is in practice — how
  many ärenden carry no priority at all on the boards where grouping is used.
  If it is more than a handful, move the group-by to `priority_label`.
- Confirm the `varchar` sort claim empirically (it follows from the column
  type, but has not been observed).
- Rehearse the migration against a restored copy of the production database —
  **never against the shared dev cluster**, per the workspace rules — and check
  the row counts per mapping bucket, especially how many `183`/`365` rows
  actually exist. If the answer is zero, open question 2 is moot.

## Follow-ups, out of scope

- OWL field widget rendering `priority_label` while sorting on `priority_days`.
- Removing `priority_expanded`'s sentinel entirely in favour of a pure integer,
  once `onecore/services/work-order` is changed to write `priority_days` — a
  cleanup with no user-visible effect, not worth a coordinated release on its
  own.
