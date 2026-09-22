# MIM-2038 Priority Mechanism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 13-entry Prioritet dropdown on a maintenance request with five fixed presets (Akut … 10 dagar) plus a *"Välj antal veckor"* option where the handläggare types the number of weeks.

**Architecture:** `priority_expanded` stays a nullable `Selection` — same field name, same type — with its long tail replaced by one `custom` sentinel. The day arithmetic moves to a new stored `Integer` `priority_days`, derived from the preset and a new `priority_weeks`, and everything that used to read the Selection's numeric value (`due_date`, sorting, filtering, grouping) reads `priority_days` instead. A stored `Char` `priority_label` renders any day count back to Swedish for display.

**Tech Stack:** Odoo 19, Python 3, `TransactionCase` tests tagged `onecore`, XML views, raw-SQL Odoo migrations.

**Spec:** `docs/superpowers/specs/2026-09-22-mim-2038-priority-mechanism-design.md` — read it before Task 1. It explains *why* the picker stays a Selection, which is not obvious from the code.

## Global Constraints

- **All user-facing strings are Swedish.** Field labels, filter captions, error messages. Code, comments and identifiers are English.
- **Commit messages are English**, and end with the `Co-Authored-By` trailer this repo's commits use.
- **`priority_expanded` keeps its name, its `Selection` type, its nullability, and `'7'` as a valid value.** `onecore/services/work-order/src/services/work-order-service/adapters/odoo-adapter/index.ts:715` writes `priority_expanded: '7'` over XML-RPC. Breaking any of those four properties breaks another repo silently.
- **Never let an `Integer` answer "is priority set?".** Odoo reads `NULL`/`False` as `0`, and Akut *is* 0 days. The set/unset question is answered by `priority_expanded` (nullable) only.
- **`priority_days` is `False` (SQL `NULL`) when no priority is set** — never `0`. `0` means Akut.
- Tests run with `./run_tests.sh` (fresh throwaway DB, `--test-tags=onecore`). There is no per-test runner; to iterate on one class, run odoo-bin directly with `--test-tags=/onecore_maintenance_extension:TestClassName`.
- Formatters: Black for Python, RedHat XML formatter for XML.
- Never `git add .` or `git add docs/` — stage files explicitly.

---

### Task 1: Pure priority helpers

The day/label arithmetic lives in one pure module so the model *and* the migration share a single implementation, and so the rules are unit-testable without an Odoo record.

**Files:**
- Create: `onecore_maintenance_extension/models/utils/priority.py`
- Modify: `onecore_maintenance_extension/models/utils/__init__.py`
- Modify: `onecore_maintenance_extension/models/constants.py:54-68`
- Test: `onecore_maintenance_extension/tests/models/test_priority.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `constants.PRIORITY_PRESETS: list[tuple[str, str]]`
  - `constants.PRIORITY_CUSTOM: str` (`"custom"`)
  - `constants.PRIORITY_MAX_WEEKS: int` (`52`)
  - `constants.LEGACY_PRIORITY_WEEKS: dict[str, int]` — legacy Selection value → weeks
  - `utils.priority.priority_days_from(preset: str | bool, weeks: int | bool) -> int | bool`
  - `utils.priority.priority_label_for(days: int | bool) -> str | bool`

- [ ] **Step 1: Write the failing test**

Create `onecore_maintenance_extension/tests/models/test_priority.py`:

```python
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.constants import PRIORITY_CUSTOM
from ...models.utils.priority import priority_days_from, priority_label_for


@tagged("onecore")
class TestPriorityHelpers(TransactionCase):
    """Pure arithmetic — no records involved, but kept in the Odoo suite so
    it runs in CI alongside everything else."""

    def test_days_from_preset(self):
        for preset, expected in (("0", 0), ("1", 1), ("5", 5), ("7", 7), ("10", 10)):
            self.assertEqual(priority_days_from(preset, False), expected)

    def test_days_from_custom_weeks(self):
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, 3), 21)
        self.assertEqual(priority_days_from(PRIORITY_CUSTOM, 26), 182)

    def test_days_is_false_when_unset(self):
        """Unset must be False, not 0 — 0 is Akut."""
        self.assertIs(priority_days_from(False, False), False)

    def test_days_is_false_when_custom_without_weeks(self):
        self.assertIs(priority_days_from(PRIORITY_CUSTOM, 0), False)
        self.assertIs(priority_days_from(PRIORITY_CUSTOM, False), False)

    def test_label_akut_is_not_confused_with_unset(self):
        self.assertEqual(priority_label_for(0), "Akut")
        self.assertIs(priority_label_for(False), False)

    def test_label_days_and_weeks(self):
        self.assertEqual(priority_label_for(1), "1 dag")
        self.assertEqual(priority_label_for(5), "5 dagar")
        self.assertEqual(priority_label_for(7), "7 dagar")
        self.assertEqual(priority_label_for(10), "10 dagar")
        self.assertEqual(priority_label_for(14), "2 veckor")
        self.assertEqual(priority_label_for(21), "3 veckor")
        self.assertEqual(priority_label_for(182), "26 veckor")

    def test_label_for_non_week_multiple_falls_back_to_days(self):
        """A legacy value that is not a whole number of weeks stays honest."""
        self.assertEqual(priority_label_for(183), "183 dagar")

    def test_legacy_mapping_is_consistent_with_the_arithmetic(self):
        """Every retired value maps to weeks the helpers agree with.

        The 19.0.1.0.12 migration writes these weeks into priority_weeks and
        lets init_models() derive priority_days from them, so a typo in the
        table would silently shift a live ärende's förfallodatum. 183 and 365
        are deliberately NOT whole weeks — they round to 182 and 364.
        """
        for value, weeks in LEGACY_PRIORITY_WEEKS.items():
            self.assertEqual(
                priority_days_from(PRIORITY_CUSTOM, weeks),
                weeks * 7,
                "legacy value %s maps to %d weeks" % (value, weeks),
            )
            self.assertLessEqual(
                abs(int(value) - weeks * 7),
                1,
                "legacy value %s must not move by more than a day" % value,
            )
```

Add `LEGACY_PRIORITY_WEEKS` to the `from ...models.constants import` line at the top of the file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `./run_tests.sh 2>&1 | grep -A5 TestPriorityHelpers`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `models.utils.priority`.

- [ ] **Step 3: Write the constants**

In `onecore_maintenance_extension/models/constants.py`, replace the `PRIORITY_OPTIONS` block at lines 54-68 with:

```python
PRIORITY_CUSTOM = "custom"

# Prioritet presets. The value of every non-custom entry IS the number of days
# to förfallodatum — see models/utils/priority.py. PRIORITY_CUSTOM is the
# escape hatch (MIM-2038): the day count then comes from priority_weeks.
# '7' must stay a valid value: onecore's work-order odoo-adapter writes it
# over XML-RPC when creating besiktning requests.
PRIORITY_PRESETS = [
    ("0", "Akut"),
    ("1", "1 dag"),
    ("5", "5 dagar"),
    ("7", "7 dagar"),
    ("10", "10 dagar"),
    (PRIORITY_CUSTOM, "Välj antal veckor"),
]

PRIORITY_MAX_WEEKS = 52

# Legacy Selection values MIM-2038 retired, mapped to the weeks that replace
# them. Consumed by migrations/19.0.1.0.12/pre-migration.py.
LEGACY_PRIORITY_WEEKS = {
    "14": 2,
    "21": 3,
    "28": 4,
    "35": 5,
    "42": 6,
    "56": 8,
    "183": 26,
    "365": 52,
}
```

- [ ] **Step 4: Write the pure helpers**

Create `onecore_maintenance_extension/models/utils/priority.py`:

```python
"""Prioritet arithmetic for maintenance requests (MIM-2038).

Kept pure and record-free so the model and the 19.0.1.0.12 migration share
one implementation of the rules rather than two that can drift.

The load-bearing convention: a day count of 0 means Akut, and False means no
priority has been chosen. They are NOT interchangeable — Odoo reads a NULL
Integer as 0, so anything that decides "is priority set?" must look at the
nullable Selection, never at the day count.
"""

from ..constants import PRIORITY_CUSTOM

DAYS_PER_WEEK = 7

# Below this many days a value reads better as days than as weeks: "7 dagar"
# rather than "1 vecka", which is also how the presets are worded.
MIN_DAYS_FOR_WEEKS = 14


def priority_days_from(preset, weeks):
    """Number of days to förfallodatum, or False when no priority is set.

    Args:
        preset: a value from constants.PRIORITY_PRESETS, or False.
        weeks: number of weeks, only meaningful when preset is PRIORITY_CUSTOM.
    """
    if not preset:
        return False
    if preset == PRIORITY_CUSTOM:
        return DAYS_PER_WEEK * weeks if weeks else False
    return int(preset)


def priority_label_for(days):
    """Swedish rendering of a day count, or False when no priority is set."""
    if days is False or days is None:
        return False
    if days == 0:
        return "Akut"
    if days >= MIN_DAYS_FOR_WEEKS and days % DAYS_PER_WEEK == 0:
        return "%d veckor" % (days // DAYS_PER_WEEK)
    if days == 1:
        return "1 dag"
    return "%d dagar" % days
```

Add to `onecore_maintenance_extension/models/utils/__init__.py`:

```python
from .priority import priority_days_from, priority_label_for
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./run_tests.sh 2>&1 | grep -E "TestPriorityHelpers|FAIL|ERROR"`
Expected: no FAIL/ERROR lines for `TestPriorityHelpers`.

Note: the suite will still fail elsewhere — `maintenance.py` imports `PRIORITY_OPTIONS`, which no longer exists. Task 2 fixes that. If you want a green run before then, do Tasks 1 and 2 back to back and commit separately.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/models/utils/priority.py \
        onecore_maintenance_extension/models/utils/__init__.py \
        onecore_maintenance_extension/models/constants.py \
        onecore_maintenance_extension/tests/models/test_priority.py
git commit -m "MIM-2038: add pure priority day/label helpers and new presets"
```

---

### Task 2: Model fields, computes and constraint

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py:23-31` (imports), `:115-119` (fields), `:844-852` (`_compute_due_date`)
- Test: `onecore_maintenance_extension/tests/models/test_priority.py` (append)

**Interfaces:**
- Consumes: `priority_days_from`, `priority_label_for`, `PRIORITY_PRESETS`, `PRIORITY_CUSTOM`, `PRIORITY_MAX_WEEKS` from Task 1.
- Produces, on `maintenance.request`:
  - `priority_expanded` — `Selection(PRIORITY_PRESETS)`, stored, nullable (unchanged name/type)
  - `priority_weeks` — `Integer`, stored
  - `priority_days` — `Integer`, stored compute, readonly, `False` when unset
  - `priority_label` — `Char`, stored compute, readonly

- [ ] **Step 1: Write the failing tests**

Append to `onecore_maintenance_extension/tests/models/test_priority.py`:

```python
from odoo.exceptions import ValidationError

from ..utils.test_utils import create_maintenance_request


@tagged("onecore")
class TestPriorityFields(TransactionCase):
    def test_preset_sets_days_and_label(self):
        request = create_maintenance_request(self.env, priority_expanded="10")
        self.assertEqual(request.priority_days, 10)
        self.assertEqual(request.priority_label, "10 dagar")

    def test_custom_weeks_sets_days_and_label(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=9
        )
        self.assertEqual(request.priority_days, 63)
        self.assertEqual(request.priority_label, "9 veckor")

    def test_changing_weeks_recomputes_days(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=2
        )
        request.write({"priority_weeks": 4})
        self.assertEqual(request.priority_days, 28)
        self.assertEqual(request.priority_label, "4 veckor")

    def test_unset_priority_leaves_days_null(self):
        """The 0-vs-NULL regression test. An unset ärende must not look like Akut."""
        request = create_maintenance_request(self.env, priority_expanded=False)
        self.assertFalse(request.priority_days)
        self.assertFalse(request.priority_label)

        akut = create_maintenance_request(self.env, priority_expanded="0")
        matches_akut = self.env["maintenance.request"].search(
            [("id", "in", (request | akut).ids), ("priority_days", "=", 0)]
        )
        self.assertEqual(matches_akut, akut, "unset must not match the Akut filter")

    def test_custom_rejects_weeks_out_of_range(self):
        for weeks in (0, -1, 53):
            with self.assertRaises(ValidationError):
                create_maintenance_request(
                    self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=weeks
                )

    def test_custom_accepts_range_bounds(self):
        for weeks in (1, 52):
            request = create_maintenance_request(
                self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=weeks
            )
            self.assertEqual(request.priority_days, weeks * 7)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh 2>&1 | grep -E "TestPriorityFields|priority_weeks|PRIORITY_OPTIONS"`
Expected: FAIL — `ImportError: cannot import name 'PRIORITY_OPTIONS'`, and `Invalid field 'priority_weeks'`.

- [ ] **Step 3: Update the imports**

In `onecore_maintenance_extension/models/maintenance.py`, in the `from .constants import (...)` block at lines 23-31, replace `PRIORITY_OPTIONS,` with:

```python
    PRIORITY_PRESETS,
    PRIORITY_CUSTOM,
    PRIORITY_MAX_WEEKS,
```

and add, next to the other `models.utils` imports:

```python
from .utils.priority import priority_days_from, priority_label_for
```

- [ ] **Step 4: Replace the field definitions**

In `maintenance.py`, replace the `priority_expanded` field at lines 115-119 with:

```python
    priority_expanded = fields.Selection(
        PRIORITY_PRESETS,
        string="Prioritet",
        store=True,
    )
    priority_weeks = fields.Integer(
        "Antal veckor",
        store=True,
        help="Antal veckor till förfallodatum. Används endast när prioritet är"
        " 'Välj antal veckor'.",
    )
    # The day count is the arithmetic priority_expanded used to carry itself.
    # False (SQL NULL) means no priority is set; 0 means Akut. Keeping those
    # distinct is why the picker above is still a nullable Selection.
    priority_days = fields.Integer(
        "Prioritet (dagar)",
        compute="_compute_priority_days",
        store=True,
        readonly=True,
    )
    priority_label = fields.Char(
        "Prioritet",
        compute="_compute_priority_label",
        store=True,
        readonly=True,
    )
```

- [ ] **Step 5: Add the computes and the constraint**

In `maintenance.py`, immediately above `_compute_due_date` (around line 844), add:

```python
    @api.depends("priority_expanded", "priority_weeks")
    def _compute_priority_days(self):
        for record in self:
            record.priority_days = priority_days_from(
                record.priority_expanded, record.priority_weeks
            )

    @api.depends("priority_days")
    def _compute_priority_label(self):
        for record in self:
            record.priority_label = priority_label_for(record.priority_days)

    @api.constrains("priority_expanded", "priority_weeks")
    def _check_priority_weeks(self):
        for record in self:
            if record.priority_expanded != PRIORITY_CUSTOM:
                continue
            if not 1 <= record.priority_weeks <= PRIORITY_MAX_WEEKS:
                raise exceptions.ValidationError(
                    _("Antal veckor måste vara mellan 1 och %s.") % PRIORITY_MAX_WEEKS
                )
```

Check the top of `maintenance.py` for how `exceptions` and `_` are imported and match it; if `exceptions` is not imported there, use `from odoo.exceptions import ValidationError` and raise `ValidationError` directly.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./run_tests.sh 2>&1 | grep -E "TestPriority|FAIL|ERROR"`
Expected: `TestPriorityHelpers` and `TestPriorityFields` pass. `TestMaintenanceRequestDueDate` still fails — Task 3.

- [ ] **Step 7: Commit**

```bash
git add onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/tests/models/test_priority.py
git commit -m "MIM-2038: derive priority_days and priority_label from the picker"
```

---

### Task 3: Point `due_date` at `priority_days`

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py:844-852`
- Modify: `onecore_maintenance_extension/tests/models/test_maintenance.py:51-140`
- Test: `onecore_maintenance_extension/tests/models/test_priority.py` (append)

**Interfaces:**
- Consumes: `priority_days` from Task 2.
- Produces: no new names. `due_date` behaviour is unchanged for every value that still exists; only its input changes.

- [ ] **Step 1: Write the failing tests**

Append to `test_priority.py`:

```python
from datetime import date, timedelta


@tagged("onecore")
class TestPriorityDueDate(TransactionCase):
    def test_due_date_from_custom_weeks(self):
        request_date = date.today()
        request = create_maintenance_request(
            self.env,
            request_date=request_date,
            priority_expanded=PRIORITY_CUSTOM,
            priority_weeks=6,
        )
        self.assertEqual(request.due_date, request_date + timedelta(days=42))

    def test_akut_due_date_is_the_base_date(self):
        """Akut is 0 days, not 'no priority' — due_date must still be set."""
        request_date = date.today()
        request = create_maintenance_request(
            self.env, request_date=request_date, priority_expanded="0"
        )
        self.assertEqual(request.due_date, request_date)

    def test_manual_due_date_survives_a_weeks_change(self):
        request = create_maintenance_request(
            self.env, priority_expanded=PRIORITY_CUSTOM, priority_weeks=2
        )
        manual = date.today() + timedelta(days=99)
        request.write({"priority_weeks": 4, "due_date": manual})
        self.assertEqual(request.due_date, manual)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./run_tests.sh 2>&1 | grep -E "TestPriorityDueDate|FAIL|ERROR"`
Expected: FAIL — `_compute_due_date` still calls `int(record.priority_expanded)`, which raises `ValueError: invalid literal for int() with base 10: 'custom'`.

- [ ] **Step 3: Rewrite `_compute_due_date`**

Replace lines 844-852 of `maintenance.py` with:

```python
    @api.depends("request_date", "start_date", "priority_days")
    def _compute_due_date(self):
        for record in self:
            base_date = record.start_date if record.start_date else record.request_date

            # `is not False` rather than a truthiness test: priority_days is 0
            # for Akut, whose förfallodatum is the base date itself.
            if base_date and record.priority_days is not False:
                record.due_date = fields.Date.add(
                    base_date, days=record.priority_days
                )
```

Leave `_inverse_due_date` exactly as it is — the no-op is what lets a manually typed förfallodatum survive a flush.

**Watch out:** Odoo may hand the compute an `int` rather than the literal `False` for an unset record. If `test_unset_priority_leaves_days_null` or an existing `test_schedule_date_warning` case fails after this change, use `if base_date and record.priority_days not in (False, None):` — and if Odoo has already coerced it to `0`, fall back to gating on `record.priority_expanded` instead, which is the nullable field and always tells the truth.

- [ ] **Step 4: Update the existing due-date tests**

In `test_maintenance.py`, the cases at lines 78, 86, 94, 107, 111, 118, 123 and 135 pass retired values. Rewrite each to the custom form. For example, line 78:

```python
        request = create_maintenance_request(
            self.env,
            request_date=request_date,
            priority_expanded=PRIORITY_CUSTOM,
            priority_weeks=26,
        )
```

Mapping to apply: `"14"` → `weeks=2`, `"42"` → `weeks=6`, `"183"` → `weeks=26`, `"365"` → `weeks=52`. Update each test's expected `due_date` to match the new day count (`26 * 7 = 182`, not 183; `52 * 7 = 364`, not 365) and add `PRIORITY_CUSTOM` to the imports at the top of the file. Leave the case at line 118 (manual `due_date` wins) asserting exactly what it asserts today.

- [ ] **Step 5: Run the full suite to verify it passes**

Run: `./run_tests.sh 2>&1 | tail -40`
Expected: no `FAIL` or `ERROR`. Every test file that seeds `priority_expanded="7"` or `"5"` or `"10"` still works — those are all still valid presets.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/tests/models/test_maintenance.py \
        onecore_maintenance_extension/tests/models/test_priority.py
git commit -m "MIM-2038: compute due_date from priority_days"
```

---

### Task 4: Stage-gate regression test

No production code changes. `maintenance_workflow_service.py:105` reads `not record.priority_expanded` and is *already* correct — this task pins that down so a later refactor toward a pure integer field fails loudly instead of silently blocking every Akut ärende.

**Files:**
- Test: `onecore_maintenance_extension/tests/models/test_priority.py` (append)

**Interfaces:**
- Consumes: `priority_days` from Task 2, the `StageTestMixin` pattern from `tests/models/test_maintenance.py:26`.
- Produces: nothing.

- [ ] **Step 1: Write the test**

Append to `test_priority.py`:

```python
from odoo.exceptions import UserError


@tagged("onecore")
class TestPriorityStageGate(TransactionCase):
    """maintenance_workflow_service gates handling stages on priority being
    set. Akut is 0 days, and Odoo reads a NULL Integer as 0 — so if that gate
    is ever moved from priority_expanded onto priority_days, every Akut ärende
    silently becomes unmovable. These two tests are the tripwire."""

    def setUp(self):
        super().setUp()
        self.stage_tilldelad = self.env["maintenance.stage"].search(
            [("name", "=", "Resurs tilldelad")]
        )

    def test_akut_request_can_move_to_a_handling_stage(self):
        request = create_maintenance_request(self.env, priority_expanded="0")
        self.assertEqual(request.priority_days, 0)
        request.write({"stage_id": self.stage_tilldelad.id})
        self.assertEqual(request.stage_id, self.stage_tilldelad)

    def test_request_without_priority_is_still_blocked(self):
        request = create_maintenance_request(self.env, priority_expanded=False)
        with self.assertRaises(UserError):
            request.write({"stage_id": self.stage_tilldelad.id})
```

- [ ] **Step 2: Run the tests**

Run: `./run_tests.sh 2>&1 | grep -E "TestPriorityStageGate|FAIL|ERROR"`
Expected: both PASS with no production change. If `test_akut_request_can_move_to_a_handling_stage` fails, the 0-vs-NULL trap has already been introduced somewhere in Tasks 2-3 — fix that before continuing rather than adjusting the test.

Note: `test_request_without_priority_is_still_blocked` may also need a `user_id`, since the same service raises "Ingen resurs är tilldelad" first (`maintenance_workflow_service.py:95`). Check which `UserError` is raised; if it is the resource one, assign a user via `create_internal_user` (see `tests/models/services/test_maintenance_workflow_service.py:204` for the established shape) so the priority gate is the one under test.

- [ ] **Step 3: Commit**

```bash
git add onecore_maintenance_extension/tests/models/test_priority.py
git commit -m "MIM-2038: pin the Akut-is-not-unset behaviour of the stage gate"
```

---

### Task 5: Form, list, kanban and mobile views

**Files:**
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml:232-236` (read-only block), `:779-781` (editable field), `:975` (kanban), `:1046` (list)
- Modify: `onecore_maintenance_extension/views/mobile_view.xml:36`

**Interfaces:**
- Consumes: `priority_weeks`, `priority_label` from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the weeks input to the editable form**

Replace the `priority_expanded` field at `maintenance_views.xml:779-781` with:

```xml
                                        <field
                                            name="priority_expanded"
                                            readonly="user_is_external_contractor" />
                                        <field
                                            name="priority_weeks"
                                            invisible="priority_expanded != 'custom'"
                                            required="priority_expanded == 'custom'"
                                            readonly="user_is_external_contractor" />
```

- [ ] **Step 2: Show the label in the read-only block**

Replace `maintenance_views.xml:231-236` with:

```xml
                    <div class="d-flex w-100 justify-content-between justify-content-md-start"
                        invisible="not priority_label">
                        <label class="me-1" for="priority_label" string="Prioritet" />
                        <field class="ms-1 text-end text-md-start" name="priority_label"
                            readonly="1" />
                    </div>
```

- [ ] **Step 3: Swap the label into kanban, list and mobile**

At `maintenance_views.xml:975`, replace `<field name="priority_expanded" />` with:

```xml
                    <field name="priority_label" />
                    <field name="priority_days" />
```

At `maintenance_views.xml:1046`, replace `<field name="priority_expanded" optional="hide" />` with:

```xml
                        <field name="priority_label" optional="hide" />
```

At `mobile_view.xml:36`, replace `<field name="priority_expanded" />` with:

```xml
        <field name="priority_label" />
```

- [ ] **Step 4: Verify in a running Odoo**

Run `./run-local-odoo.sh onecore_maintenance_extension`, open a maintenance request and confirm:
- Picking *Välj antal veckor* reveals the **Antal veckor** field; picking anything else hides it.
- Typing `9` sets Förfallodatum to request/start date + 63 days.
- Saving with *Välj antal veckor* and an empty weeks field is refused.
- The read-only Prioritet block near Ärendebeskrivning reads "9 veckor", not "custom".
- The list's Prioritet column (enable it via the optional-columns toggle) reads the label.

`priority_label` is a stored `Char`, so sorting that column sorts alphabetically. That is expected here — see Task 8.

- [ ] **Step 5: Commit**

```bash
git add onecore_maintenance_extension/views/maintenance_views.xml \
        onecore_maintenance_extension/views/mobile_view.xml
git commit -m "MIM-2038: add the weeks input and show the rendered priority label"
```

---

### Task 6: Search filters and group-by

The 11 per-value quick-filters cannot survive a free value. They are replaced by four ranges over `priority_days` plus a group-by.

**Files:**
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml:46-67` (filters), `:124-141` (group-by block)

**Interfaces:**
- Consumes: `priority_days` from Task 2.
- Produces: nothing.

- [ ] **Step 1: Replace the eleven filters**

Replace `maintenance_views.xml:46-67` (the block from `<filter string="Akut"` through `name="eight_weeks"`) with:

```xml
                        <!-- MIM-2038: ranges rather than one filter per value —
                             antal veckor is free-form, so a filter per literal
                             value is no longer writable. -->
                        <filter string="Akut" name="priority_acute"
                            domain="[('priority_days', '=', 0)]" />
                        <filter string="Inom 7 dagar" name="priority_week"
                            domain="[('priority_days', '&gt;', 0), ('priority_days', '&lt;=', 7)]" />
                        <filter string="8–30 dagar" name="priority_month"
                            domain="[('priority_days', '&gt;', 7), ('priority_days', '&lt;=', 30)]" />
                        <filter string="Längre än 30 dagar" name="priority_long"
                            domain="[('priority_days', '&gt;', 30)]" />
```

`('priority_days', '=', 0)` matches Akut and **not** unset, because unset is SQL `NULL`. Task 2's `test_unset_priority_leaves_days_null` covers exactly this.

- [ ] **Step 2: Add the group-by**

Inside the `<group>` block at `maintenance_views.xml:124-141`, after the `ordering_department` filter, add:

```xml
                            <filter string='Prioritet' name='priority' domain="[]"
                                context="{'group_by': 'priority_days'}" />
```

- [ ] **Step 3: Verify in a running Odoo**

Run `./run-local-odoo.sh onecore_maintenance_extension` and confirm:
- All four priority filters return plausible sets and an ärende with no priority appears in none of them.
- Grouping by Prioritet orders groups numerically (`0, 1, 5, 7, 10, 14, …`) rather than as text.
- The old filter names are gone from the Filter menu with no console error — a saved user filter referencing a removed `name` is the thing most likely to complain here.
- **Where unset ärenden land when sorting on `priority_days`.** The spec flags this as unverified: `priority_days` is `NULL` for them, and Postgres sorts `NULL` last ascending, but Odoo may add its own `NULLS FIRST/LAST`. Sort the column both ways with at least one unprioritised ärende present and record what actually happens. If they land at the top of an ascending sort and that reads as wrong, say so rather than fixing it here — it is a view-level `order` change, not a model change.

- [ ] **Step 4: Commit**

```bash
git add onecore_maintenance_extension/views/maintenance_views.xml
git commit -m "MIM-2038: replace per-value priority filters with ranges and a group-by"
```

---

### Task 7: Migration 19.0.1.0.12

**Files:**
- Create: `onecore_maintenance_extension/migrations/19.0.1.0.12/pre-migration.py`
- Create: `onecore_maintenance_extension/migrations/19.0.1.0.12/post-migration.py`
- Modify: `onecore_maintenance_extension/__manifest__.py:6`

**Interfaces:**
- Consumes: `constants.LEGACY_PRIORITY_WEEKS`, `constants.PRIORITY_CUSTOM` from Task 1.
- Produces: nothing consumed by later tasks.

Read `migrations/19.0.1.0.7/pre-migration.py` first — its docstring spells out Odoo's pre → `init_models()` → post ordering, which is the whole reason this task is split across two files.

- [ ] **Step 1: Bump the manifest version**

In `onecore_maintenance_extension/__manifest__.py:6`, change `"version": "19.0.1.0.11",` to `"version": "19.0.1.0.12",`.

- [ ] **Step 2: Write the pre-migration**

Create `onecore_maintenance_extension/migrations/19.0.1.0.12/pre-migration.py`:

```python
"""MIM-2038 — remap the retired priority values onto the custom-weeks escape.

priority_expanded used to carry the day count in its own Selection value
("14" = 2 veckor, "183" = 6 månader). MIM-2038 keeps only the short presets
and replaces the long tail with PRIORITY_CUSTOM plus a priority_weeks integer,
so every row still sitting on a retired value has to be remapped BEFORE
init_models() validates the column against the new, shorter selection list.

Odoo runs every applicable pre-migration, THEN init_models() (which creates
any column the current field definitions declare and fills newly-added stored
computes for every existing row), THEN every post-migration — the ordering
documented in migrations/19.0.1.0.7/pre-migration.py. Two consequences shape
this script:

  - priority_weeks does not exist yet. init_models() has not run, so the
    column has to be created here by hand or step 3 has nowhere to write.
  - priority_days and priority_label are brand-new stored computes.
    init_models() will fill them for every row from whatever this script
    leaves in priority_expanded and priority_weeks, so getting those two
    right here is all that is needed — exactly the mechanism
    migrations/19.0.1.0.10/post-migration.py describes for
    lease_status_label.

The due_date backup is defensive. Raw SQL does not retrigger an existing
stored compute, so the priority_expanded rewrite alone would leave due_date
alone — but due_date @api.depends on priority_days, which init_models() fills
through the ORM, and that fill may well mark due_date dirty. Whether it
actually does has not been established, and the two outcomes differ on real
data: 183 -> 26 veckor is 182 days, so a recompute would move a live ärende's
förfallodatum by a day, and any ärende with a hand-typed due_date (which
_inverse_due_date exists to protect) would be overwritten. Backing the column
up here and restoring it in post-migration makes the outcome the same either
way: no ärende's förfallodatum changes.

Idempotent: the UPDATE is guarded on the retired values, which no longer
exist after a successful run, and both ADD COLUMNs use IF NOT EXISTS.
"""

import logging

from odoo.addons.onecore_maintenance_extension.models.constants import (
    LEGACY_PRIORITY_WEEKS,
    PRIORITY_CUSTOM,
)

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def migrate(cr, version):
    _add_columns(cr)
    _backup_due_date(cr)
    _remap_retired_values(cr)


def _add_columns(cr):
    cr.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS priority_weeks integer')
    cr.execute(f'ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS "{DUE_DATE_BACKUP}" date')


def _backup_due_date(cr):
    cr.execute(f'UPDATE {TABLE} SET "{DUE_DATE_BACKUP}" = due_date')
    _logger.info("MIM-2038: backed up due_date on %d request(s).", cr.rowcount)


def _remap_retired_values(cr):
    """Retired value -> PRIORITY_CUSTOM + the equivalent number of weeks."""
    when_clauses = "\n            ".join(
        f"WHEN '{value}' THEN {weeks}" for value, weeks in LEGACY_PRIORITY_WEEKS.items()
    )
    values = tuple(LEGACY_PRIORITY_WEEKS)

    cr.execute(
        f"""
        UPDATE {TABLE}
        SET priority_weeks = CASE priority_expanded
            {when_clauses}
            END,
            priority_expanded = %s
        WHERE priority_expanded IN %s
        """,
        (PRIORITY_CUSTOM, values),
    )
    _logger.info(
        "MIM-2038: remapped %d request(s) from a retired priority value.", cr.rowcount
    )
```

- [ ] **Step 3: Write the post-migration**

Create `onecore_maintenance_extension/migrations/19.0.1.0.12/post-migration.py`:

```python
"""MIM-2038 — restore förfallodatum to its pre-upgrade value.

See migrations/19.0.1.0.12/pre-migration.py for why the backup exists: this
script is the half that guarantees no ärende's förfallodatum moved, whether or
not init_models() recomputed it while filling the new priority_days column.

Idempotent: the restore is guarded on IS DISTINCT FROM and the backup column
is dropped once it has been applied, so a second run finds nothing to do.
"""

import logging

from odoo import api, SUPERUSER_ID
from odoo.tools.sql import column_exists

_logger = logging.getLogger(__name__)

TABLE = "maintenance_request"
DUE_DATE_BACKUP = "_mim2038_due_date_backup"


def migrate(cr, version):
    if not column_exists(cr, TABLE, DUE_DATE_BACKUP):
        _logger.info("MIM-2038: no due_date backup column — nothing to restore.")
        return

    cr.execute(f"""
        UPDATE {TABLE}
        SET due_date = "{DUE_DATE_BACKUP}"
        WHERE due_date IS DISTINCT FROM "{DUE_DATE_BACKUP}"
    """)
    _logger.info("MIM-2038: restored due_date on %d request(s).", cr.rowcount)

    cr.execute(f'ALTER TABLE {TABLE} DROP COLUMN "{DUE_DATE_BACKUP}"')

    # Every statement above wrote via raw SQL, so anything already in cache
    # would keep serving pre-UPDATE values for the rest of this upgrade.
    api.Environment(cr, SUPERUSER_ID, {}).invalidate_all()
```

- [ ] **Step 4: Rehearse the migration on a local database**

The migration cannot be exercised by `run_tests.sh`, which always starts from an empty database. Rehearse it by hand, **locally only** — never against the dev cluster, and never against Xpand:

```bash
# 1. On the PREVIOUS commit (before Task 1), start Odoo and let it install
#    the module at 19.0.1.0.11:
git stash push -u -m "mim-2038-wip" && git checkout <sha-before-task-1>
./run-local-odoo.sh onecore_maintenance_extension
# 2. In the UI, create requests covering every retired value: 14, 42, 56,
#    183, 365 — plus one with a hand-typed Förfallodatum, and one Akut.
#    Record each one's Förfallodatum.
# 3. Return to the branch and upgrade in place:
git checkout - && git stash list --format='%H %gs'   # re-find your entry by tag
git stash apply <sha> && git stash drop <its stash@{n}>
./run-local-odoo.sh onecore_maintenance_extension    # runs the upgrade
```

Then confirm, for each request created in step 2:
- Prioritet reads *Välj antal veckor* with the expected Antal veckor (2, 6, 8, 26, 52).
- **Förfallodatum is byte-identical to what you recorded** — including the hand-typed one. This is the assertion the whole backup/restore pair exists for.
- The Akut request still reads Akut, still has `priority_days = 0`, and still moves to Resurs tilldelad.
- The log contains the three `MIM-2038:` lines with non-zero counts.

Re-run `./run-local-odoo.sh` once more and confirm the second pass logs
"no due_date backup column — nothing to restore" and changes nothing.

- [ ] **Step 5: Commit**

```bash
git add onecore_maintenance_extension/migrations/19.0.1.0.12/pre-migration.py \
        onecore_maintenance_extension/migrations/19.0.1.0.12/post-migration.py \
        onecore_maintenance_extension/__manifest__.py
git commit -m "MIM-2038: migrate retired priority values onto custom weeks"
```

---

### Task 8: Translations, stale comment, and full verification

**Files:**
- Modify: `onecore_maintenance_extension/i18n/sv.po`
- Modify: `onecore_maintenance_extension/static/src/js/schedule_date_validation.js:16`

**Interfaces:**
- Consumes: every string introduced in Tasks 1-7.
- Produces: nothing.

- [ ] **Step 1: Fix the stale comment**

In `schedule_date_validation.js:16`, the docstring says "A priority_expanded change that recomputes due_date backwards". A `priority_weeks` edit now reaches `due_date` down the same path, so widen the wording:

```javascript
 * Only direct edits of the two date fields prompt. A priority change (preset
 * or antal veckor) that recomputes due_date backwards arrives via the onchange
 * result rather than the change set, and is surfaced by the
 * schedule_date_after_due_date warning in the form and kanban instead.
```

- [ ] **Step 2: Check the translation file**

Check whether `i18n/sv.po` carries entries for the old priority labels:

```bash
grep -n "Akut\|veckor\|Prioritet" onecore_maintenance_extension/i18n/sv.po
```

If there are none (the labels are Swedish literals in the Python source, so there may not be), this step is a no-op — say so and move on. If there are, add entries for "Antal veckor", "Välj antal veckor", "Prioritet (dagar)", the four new filter captions and the constraint message, following the file's existing format.

- [ ] **Step 3: Run the full suite**

Run: `./run_tests.sh 2>&1 | tail -60`
Expected: zero `FAIL`, zero `ERROR`.

- [ ] **Step 4: Confirm nothing still references the removed name**

```bash
grep -rn "PRIORITY_OPTIONS" onecore_maintenance_extension/
```

Expected: no output. Then check that `priority_expanded` survives only where it should — the model field, the workflow-service gate, the form's editable field, and test seeds:

```bash
grep -rn "priority_expanded" onecore_maintenance_extension/ --exclude-dir=migrations
```

Anything in a *list*, *kanban*, *mobile* or *filter* context is a leftover from Tasks 5-6.

- [ ] **Step 5: Verify the cross-repo write still works**

The single onecore write must still be accepted. With a local Odoo running, confirm `'7'` is still a valid Selection value:

```bash
grep -n '("7", "7 dagar")' onecore_maintenance_extension/models/constants.py
```

Expected: one match. If this is ever not true, `onecore/services/work-order/.../odoo-adapter/index.ts:715` starts failing to create besiktning requests.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/static/src/js/schedule_date_validation.js \
        onecore_maintenance_extension/i18n/sv.po
git commit -m "MIM-2038: refresh the priority wording in comments and translations"
```

---

## Deliberately out of scope

- **An OWL widget that renders `priority_label` while sorting on `priority_days`.** Until it exists, the visible Prioritet column sorts alphabetically. The numeric column exists and grouping is correct, which is the part the spec's sorting note was about.
- **Removing the `custom` sentinel in favour of a pure integer**, which would require changing `onecore/services/work-order` and coordinating a two-repo release for no user-visible gain.
- **Answers to the five open questions for verksamheten** in the spec. Each is a one-line change: questions 1-3 touch `constants.py` only (Task 1), question 4 touches the search view only (Task 6), and a *yes* to question 5 replaces this plan entirely.
