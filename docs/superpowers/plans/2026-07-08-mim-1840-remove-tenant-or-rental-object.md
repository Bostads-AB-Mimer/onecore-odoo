# Remove tenant or rental object (MIM-1840) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trashcan icons beside the existing pen icons so an editor can remove the rental object (object-only) or the tenant (tenant + contract → vacate) from a maintenance request.

**Architecture:** Two `type="object"` buttons on `maintenance.request` (`action_remove_rental_object`, `action_remove_tenant`) use Odoo's native `confirm="…"` for the destructive-action guard and delegate the mutation to new `RecordManagementService` methods (`remove_rental_object`, `remove_tenant`). Both share a `unlink_record` best-effort delete helper that the MIM-1841 backfill wizard is refactored to reuse. A server-side permission guard mirrors the buttons' UI gate.

**Tech Stack:** Odoo 19, Python (Black), XML views, SCSS. Tests via `pytest`-style Odoo `TransactionCase` (`./run_tests.sh`).

## Global Constraints

- All user-facing text (button titles, confirm prompts, error messages) is in **Swedish**.
- Follow existing conventions (CLAUDE.md): Service Pattern for domain logic, `_compute_*`/`_onchange_*`/`action_*` naming, `string=` on fields, Black formatting.
- "Who may edit object/tenant" = member of `maintenance.group_equipment_manager` **AND** not an external contractor (`onecore_maintenance_extension.group_external_contractor`).
- Removal semantics: **remove object** clears the object field only (lease + tenant untouched); **remove tenant** clears `tenant_id` + `lease_id`, sets `manually_vacated=True` (object untouched).
- Backfillable space types only: `Lägenhet`, `Bilplats`, `Lokal`.
- No new model, view file, `__manifest__.py` entry, or `ir.model.access.csv` row (Approach A).
- Tests use `@tagged("onecore")` and inherit `TransactionCase`.

---

## File Structure

- `models/services/record_management_service.py` — add `unlink_record`, `remove_rental_object`, `remove_tenant`; add `all_routes` import. (Domain logic for removal.)
- `models/backfill_wizard.py` — refactor `_unlink_replaced` to delegate to `RecordManagementService.unlink_record` (one unlink implementation).
- `models/maintenance.py` — add `_ensure_can_edit_object_or_tenant` guard + `action_remove_rental_object` / `action_remove_tenant`; add `AccessError` import.
- `views/maintenance_views.xml` — wrap each section header's pen + new trash in a flex container.
- `static/src/scss/mimer_styles.scss` — only if the two-icon layout needs adjustment (existing `.o-section-edit-btn` z-index rule already covers both).
- `tests/models/test_remove.py` — new test module for the service methods, the action methods, and the permission guard.

---

## Task 1: Shared `unlink_record` helper + backfill refactor

**Files:**
- Modify: `onecore_maintenance_extension/models/services/record_management_service.py`
- Modify: `onecore_maintenance_extension/models/backfill_wizard.py:197-213`
- Test: `onecore_maintenance_extension/tests/models/test_remove.py` (create)

**Interfaces:**
- Produces: `RecordManagementService.unlink_record(record)` — best-effort delete of one permanent record; returns `None`; never raises on a blocked delete.

- [ ] **Step 1: Write the failing tests**

Create `onecore_maintenance_extension/tests/models/test_remove.py`:

```python
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError

from ...models.services import record_management_service
from ...models.services.external_contractor_service import ExternalContractorService
from ...models.services.record_management_service import RecordManagementService
from ..utils.test_utils import (
    create_maintenance_request,
    create_rental_property,
    create_lease,
    create_tenant,
)

SOFT_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


@tagged("onecore")
class TestRemoveUnlinkRecord(TransactionCase):
    def setUp(self):
        super().setUp()
        # Guarantee the acting user passes the edit-permission guard.
        self.env.user.group_ids = [
            (4, self.env.ref("maintenance.group_equipment_manager").id)
        ]

    def test_unlink_record_deletes_permanent_record(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        rp_id = rp.id
        RecordManagementService(self.env).unlink_record(rp)
        self.assertFalse(
            self.env["maintenance.rental.property"].browse(rp_id).exists()
        )

    def test_unlink_record_best_effort_on_blocked_delete(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        rp_id = rp.id
        with patch.object(type(rp), "unlink", side_effect=Exception("blocked")):
            # Must not raise.
            RecordManagementService(self.env).unlink_record(rp)
        self.assertTrue(
            self.env["maintenance.rental.property"].browse(rp_id).exists()
        )

    def test_unlink_record_noop_on_empty(self):
        empty = self.env["maintenance.rental.property"].browse(False)
        RecordManagementService(self.env).unlink_record(empty)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh` (or the project's single-file equivalent) targeting `test_remove.py`.
Expected: FAIL — `AttributeError: 'RecordManagementService' object has no attribute 'unlink_record'`.

- [ ] **Step 3: Add `unlink_record` to the service**

In `onecore_maintenance_extension/models/services/record_management_service.py`, add the method to the `RecordManagementService` class (place it near the other helper methods, e.g. after `handle_empty_tenant_logic`):

```python
    def unlink_record(self, record):
        """Best-effort delete of a permanent record being removed or replaced.

        If the delete is blocked (e.g. a reference elsewhere), log a warning and
        leave the record unreferenced rather than failing the caller.
        """
        if not record or not record.exists():
            return
        try:
            record.unlink()
        except Exception as err:
            _logger.warning(
                "Could not delete %s record %s: %s", record._name, record.id, err
            )
```

- [ ] **Step 4: Refactor backfill `_unlink_replaced` to delegate**

In `onecore_maintenance_extension/models/backfill_wizard.py`, replace the existing `_unlink_replaced` method (lines ~197-213) with:

```python
    def _unlink_replaced(self, old_record, new_record):
        """Delete a permanent record that was just replaced by ``new_record``."""
        if old_record and old_record != new_record:
            RecordManagementService(self.env).unlink_record(old_record)
```

(`RecordManagementService` is already imported at the top of `backfill_wizard.py`. The `not old_record` / `exists()` / try-except handling now lives in `unlink_record`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh` targeting `test_remove.py` and `test_backfill_wizard.py`.
Expected: PASS — the three new tests pass and the existing backfill wizard tests (which exercise `_unlink_replaced` via `action_confirm`) still pass.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/models/services/record_management_service.py \
        onecore_maintenance_extension/models/backfill_wizard.py \
        onecore_maintenance_extension/tests/models/test_remove.py
git commit -m "refactor(mim-1840): extract shared unlink_record helper into RecordManagementService"
```

---

## Task 2: `remove_rental_object` + `remove_tenant` service methods

**Files:**
- Modify: `onecore_maintenance_extension/models/services/record_management_service.py`
- Test: `onecore_maintenance_extension/tests/models/test_remove.py`

**Interfaces:**
- Consumes: `RecordManagementService.unlink_record` (Task 1); `all_routes()` from `direct_lookup_service` (returns route dicts with a `"record_field"` key: `rental_property_id` / `parking_space_id` / `facility_id`).
- Produces:
  - `RecordManagementService.remove_rental_object(request)` — clears whichever object field is set and unlinks that record; leaves `lease_id` / `tenant_id` untouched. Returns `None`.
  - `RecordManagementService.remove_tenant(request)` — clears `tenant_id` + `lease_id`, unlinks both, sets `request.manually_vacated = True`; leaves the object untouched. Returns `None`.

- [ ] **Step 1: Write the failing tests**

Append to `onecore_maintenance_extension/tests/models/test_remove.py`:

```python
@tagged("onecore")
class TestRemoveServiceMethods(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.group_ids = [
            (4, self.env.ref("maintenance.group_equipment_manager").id)
        ]

    def _request_with_object_lease_tenant(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        lease = create_lease(self.env, maintenance_request_id=request.id)
        tenant = create_tenant(self.env, maintenance_request_id=request.id)
        request.write(
            {
                "rental_property_id": rp.id,
                "lease_id": lease.id,
                "tenant_id": tenant.id,
            }
        )
        return request, rp, lease, tenant

    def test_remove_rental_object_clears_and_unlinks_object_only(self):
        request, rp, lease, tenant = self._request_with_object_lease_tenant()
        rp_id = rp.id
        RecordManagementService(self.env).remove_rental_object(request)
        self.assertFalse(request.rental_property_id)
        self.assertFalse(
            self.env["maintenance.rental.property"].browse(rp_id).exists()
        )
        # Lease and tenant are left untouched.
        self.assertEqual(request.lease_id, lease)
        self.assertEqual(request.tenant_id, tenant)

    def test_remove_tenant_vacates_and_unlinks_lease_and_tenant(self):
        request, rp, lease, tenant = self._request_with_object_lease_tenant()
        lease_id, tenant_id = lease.id, tenant.id
        RecordManagementService(self.env).remove_tenant(request)
        self.assertFalse(request.tenant_id)
        self.assertFalse(request.lease_id)
        self.assertTrue(request.manually_vacated)
        self.assertFalse(self.env["maintenance.lease"].browse(lease_id).exists())
        self.assertFalse(self.env["maintenance.tenant"].browse(tenant_id).exists())
        # Object is left untouched.
        self.assertEqual(request.rental_property_id, rp)

    def test_remove_tenant_does_not_refetch_on_render(self):
        request, rp, lease, tenant = self._request_with_object_lease_tenant()
        svc = RecordManagementService(self.env)
        svc.remove_tenant(request)
        # After vacating, the empty-tenant logic must NOT call the OneCore API.
        with patch.object(record_management_service, "core_api") as mock_core_api:
            svc.handle_empty_tenant_logic(request)
            mock_core_api.CoreApi.assert_not_called()
        self.assertFalse(request.lease_id)
        self.assertFalse(request.tenant_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh` targeting `test_remove.py`.
Expected: FAIL — `AttributeError: 'RecordManagementService' object has no attribute 'remove_rental_object'`.

- [ ] **Step 3: Add the `all_routes` import**

In `onecore_maintenance_extension/models/services/record_management_service.py`, add to the local imports block (below `from ....onecore_api import core_api`):

```python
from .direct_lookup_service import all_routes
```

(Verified safe: `direct_lookup_service` imports handlers, and no handler imports `RecordManagementService`, so there is no import cycle.)

- [ ] **Step 4: Add `remove_rental_object` and `remove_tenant`**

Add both methods to `RecordManagementService` (next to `unlink_record`):

```python
    def remove_rental_object(self, request):
        """Detach and unlink the request's rental object.

        Object-only: the lease and tenant are intentionally left untouched.
        """
        for route in all_routes():
            field = route["record_field"]
            old = request[field]
            if old:
                request[field] = False
                self.unlink_record(old)

    def remove_tenant(self, request):
        """Vacate the request: detach and unlink the tenant and its contract.

        Sets ``manually_vacated`` so the empty-tenant auto-refetch does not
        silently re-populate the lease/tenant. The rental object is untouched.
        """
        old_lease = request.lease_id
        old_tenant = request.tenant_id
        request.write({"lease_id": False, "tenant_id": False, "manually_vacated": True})
        self.unlink_record(old_tenant)
        self.unlink_record(old_lease)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh` targeting `test_remove.py`.
Expected: PASS — all five tests in the two classes pass.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/models/services/record_management_service.py \
        onecore_maintenance_extension/tests/models/test_remove.py
git commit -m "feat(mim-1840): remove_rental_object and remove_tenant service methods"
```

---

## Task 3: Permission guard + action methods on `maintenance.request`

**Files:**
- Modify: `onecore_maintenance_extension/models/maintenance.py:9` (imports), and near the `open_backfill_*` methods (`:1176-1198`)
- Test: `onecore_maintenance_extension/tests/models/test_remove.py`

**Interfaces:**
- Consumes: `RecordManagementService.remove_rental_object` / `remove_tenant` (Task 2); `ExternalContractorService` (already imported in `maintenance.py`).
- Produces:
  - `maintenance.request._ensure_can_edit_object_or_tenant()` — raises `AccessError` unless the current user is an equipment manager and not an external contractor.
  - `maintenance.request.action_remove_rental_object()` / `action_remove_tenant()` — guard, mutate via the service, return the `soft_reload` client action dict.

- [ ] **Step 1: Write the failing tests**

Append to `onecore_maintenance_extension/tests/models/test_remove.py`:

```python
@tagged("onecore")
class TestRemoveActions(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.group_ids = [
            (4, self.env.ref("maintenance.group_equipment_manager").id)
        ]

    def test_action_remove_rental_object_returns_soft_reload(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        request.rental_property_id = rp.id
        result = request.action_remove_rental_object()
        self.assertEqual(result, SOFT_RELOAD)
        self.assertFalse(request.rental_property_id)

    def test_action_remove_tenant_returns_soft_reload(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        lease = create_lease(self.env, maintenance_request_id=request.id)
        tenant = create_tenant(self.env, maintenance_request_id=request.id)
        request.write({"lease_id": lease.id, "tenant_id": tenant.id})
        result = request.action_remove_tenant()
        self.assertEqual(result, SOFT_RELOAD)
        self.assertFalse(request.tenant_id)
        self.assertFalse(request.lease_id)
        self.assertTrue(request.manually_vacated)

    def test_action_remove_blocked_for_external_contractor(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        request.rental_property_id = rp.id
        # Acting user is an equipment manager (setUp); force the external-contractor
        # branch so the guard is what raises, isolated from record rules.
        with patch.object(
            ExternalContractorService, "is_external_contractor", return_value=True
        ):
            with self.assertRaises(AccessError):
                request.action_remove_rental_object()
        # Nothing was mutated.
        self.assertTrue(request.rental_property_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./run_tests.sh` targeting `test_remove.py`.
Expected: FAIL — `AttributeError: 'maintenance.request' object has no attribute 'action_remove_rental_object'`.

- [ ] **Step 3: Add the `AccessError` import**

In `onecore_maintenance_extension/models/maintenance.py`, add below `from odoo import api, fields, models, _` (line 9):

```python
from odoo.exceptions import AccessError
```

- [ ] **Step 4: Add the guard and action methods**

In `onecore_maintenance_extension/models/maintenance.py`, immediately after `_open_backfill_wizard` (ends at line ~1198), add:

```python
    def _ensure_can_edit_object_or_tenant(self):
        """Raise unless the current user may edit a request's object/tenant.

        Mirrors the visibility gate on the add/change (pen) and remove (trash)
        buttons: an equipment manager who is not an external contractor. The UI
        hides the buttons; this guards the destructive server action against a
        crafted RPC call.
        """
        is_external = ExternalContractorService(self.env).is_external_contractor()
        is_manager = self.env.user.has_group("maintenance.group_equipment_manager")
        if is_external or not is_manager:
            raise AccessError(
                _("Du har inte behörighet att ändra hyresobjekt eller hyresgäst.")
            )

    def action_remove_rental_object(self):
        self.ensure_one()
        self._ensure_can_edit_object_or_tenant()
        RecordManagementService(self.env).remove_rental_object(self)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_remove_tenant(self):
        self.ensure_one()
        self._ensure_can_edit_object_or_tenant()
        RecordManagementService(self.env).remove_tenant(self)
        return {"type": "ir.actions.client", "tag": "soft_reload"}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./run_tests.sh` targeting `test_remove.py`.
Expected: PASS — all three action tests pass.

- [ ] **Step 6: Commit**

```bash
git add onecore_maintenance_extension/models/maintenance.py \
        onecore_maintenance_extension/tests/models/test_remove.py
git commit -m "feat(mim-1840): action_remove_rental_object/tenant with edit-permission guard"
```

---

## Task 4: Trash buttons in the section headers (view + styling)

**Files:**
- Modify: `onecore_maintenance_extension/views/maintenance_views.xml` (Objektsinformation header ~`:206-228`; Hyresgäst header ~`:474-494`)
- Modify: `onecore_maintenance_extension/static/src/scss/mimer_styles.scss` (only if needed)

**Interfaces:**
- Consumes: `action_remove_rental_object` / `action_remove_tenant` (Task 3); existing `open_backfill_*` methods (moved into the flex wrapper).

> No automated test — this repo has no JS/XML test harness. Verify manually by running Odoo (Step 3).

- [ ] **Step 1: Wrap the Objektsinformation header pen + add the trash**

In `onecore_maintenance_extension/views/maintenance_views.xml`, in the **Objektsinformation** `<h2 class="accordion-header … o-backfill-header">`, replace the standalone pen button (`name="open_backfill_rental_object_wizard"`, currently `class="… position-absolute top-50 end-0 translate-middle-y me-3 o-section-edit-btn"`) with a flex wrapper holding the pen **and** the trash:

```xml
<div class="position-absolute top-50 end-0 translate-middle-y me-3 d-flex gap-2 o-section-header-actions">
    <!-- MIM-1841: add/change rental object -->
    <button name="open_backfill_rental_object_wizard"
        type="object"
        groups="maintenance.group_equipment_manager"
        class="btn btn-link p-0 o-section-edit-btn"
        title="Lägg till / ändra hyresobjekt"
        invisible="not create_date or user_is_external_contractor or space_caption not in ('Lägenhet', 'Bilplats', 'Lokal')">
        <i class="fa fa-pencil" />
    </button>
    <!-- MIM-1840: remove rental object (object only; lease/tenant untouched) -->
    <button name="action_remove_rental_object"
        type="object"
        groups="maintenance.group_equipment_manager"
        class="btn btn-link p-0 o-section-edit-btn"
        title="Ta bort hyresobjekt"
        confirm="Ta bort hyresobjektet från ärendet? Detta kan inte ångras."
        invisible="not create_date or user_is_external_contractor or space_caption not in ('Lägenhet', 'Bilplats', 'Lokal') or (not rental_property_id and not parking_space_id and not facility_id)">
        <i class="fa fa-trash" />
    </button>
</div>
```

- [ ] **Step 2: Wrap the Hyresgäst header pen + add the trash**

In the **Hyresgäst** `<h2 class="accordion-header … o-backfill-header">`, replace the standalone pen button (`name="open_backfill_tenant_wizard"`) with:

```xml
<div class="position-absolute top-50 end-0 translate-middle-y me-3 d-flex gap-2 o-section-header-actions">
    <!-- MIM-1841: add/change tenant -->
    <button name="open_backfill_tenant_wizard"
        type="object"
        groups="maintenance.group_equipment_manager"
        class="btn btn-link p-0 o-section-edit-btn"
        title="Lägg till / ändra hyresgäst"
        invisible="not create_date or user_is_external_contractor or space_caption not in ('Lägenhet', 'Bilplats', 'Lokal')">
        <i class="fa fa-pencil" />
    </button>
    <!-- MIM-1840: remove tenant + contract (vacate; object untouched) -->
    <button name="action_remove_tenant"
        type="object"
        groups="maintenance.group_equipment_manager"
        class="btn btn-link p-0 o-section-edit-btn"
        title="Ta bort hyresgäst"
        confirm="Ta bort hyresgästen och kontraktet från ärendet? Ärendet blir tomställt."
        invisible="not create_date or user_is_external_contractor or space_caption not in ('Lägenhet', 'Bilplats', 'Lokal') or (not lease_id and not tenant_id)">
        <i class="fa fa-trash" />
    </button>
</div>
```

- [ ] **Step 3: Run Odoo and verify the icons**

Run: `./run-local-odoo.sh`, open an existing maintenance request of a rentalId-bearing type (Lägenhet/Bilplats/Lokal) as an equipment manager.
Verify:
- Both section headers show a pen **and** a trash icon, side by side, staying visible on hover (the existing `.o-backfill-header` z-index rule).
- The object trash is hidden when no object is attached; the tenant trash is hidden when no lease/tenant is attached.
- Clicking a trash pops the Swedish confirm dialog; confirming removes the entity and the form reloads showing the change.
- As an external contractor, neither trash (nor pen) is visible.

- [ ] **Step 4: Adjust SCSS only if needed**

If the two icons overlap or the trash paints under the accordion header on hover, add the wrapper to the existing rule in `onecore_maintenance_extension/static/src/scss/mimer_styles.scss` (the `.o-section-edit-btn { z-index: 5; }` rule already applies to both buttons since they keep that class; a change is likely unnecessary). If a gap/alignment fix is required:

```scss
.o-backfill-header {
    .o-section-header-actions {
        z-index: 5;
    }
}
```

- [ ] **Step 5: Commit**

```bash
git add onecore_maintenance_extension/views/maintenance_views.xml \
        onecore_maintenance_extension/static/src/scss/mimer_styles.scss
git commit -m "feat(mim-1840): trash icons to remove object/tenant in section headers"
```

---

## Self-Review

**Spec coverage:**
- Trash beside pen, both headers → Task 4. ✓
- Remove object = object-only → Task 2 `remove_rental_object` + test. ✓
- Remove tenant = tenant + lease + `manually_vacated` → Task 2 `remove_tenant` + tests. ✓
- Native `confirm` (Approach A), no new model/view/access → Task 4 buttons. ✓
- Unlink (delete) best-effort, shared with backfill → Task 1. ✓
- No-refetch guarantee (`manually_vacated`) → Task 2 `test_remove_tenant_does_not_refetch_on_render`. ✓
- Permission: UI gate + server-side guard → Task 3 + Task 4 `groups`/`invisible`. ✓
- Visibility only when something to remove → Task 4 `invisible` presence clauses. ✓

**Placeholder scan:** none — every code and command step is concrete.

**Type consistency:** `unlink_record(record)`, `remove_rental_object(request)`, `remove_tenant(request)`, `_ensure_can_edit_object_or_tenant()`, `action_remove_rental_object()`, `action_remove_tenant()`, and `SOFT_RELOAD` are used identically across tasks and tests. `all_routes()` route dicts use `record_field` as in `direct_lookup_service`. ✓
