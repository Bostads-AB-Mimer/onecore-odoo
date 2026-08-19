from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import AccessError

from ...models.services.record_management_service import RecordManagementService
from ..utils.test_utils import (
    create_maintenance_request,
    create_rental_property,
    create_parking_space,
    create_facility,
    create_lease,
    create_tenant,
    create_external_contractor_user,
    create_internal_user,
)

SOFT_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


@tagged("onecore")
class TestRemoveUnlinkRecord(TransactionCase):
    """The shared best-effort delete both removal paths lean on."""

    def _rental_property(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        return create_rental_property(self.env, maintenance_request_id=request.id)

    def test_unlink_record_deletes_permanent_record(self):
        rp = self._rental_property()
        rp_id = rp.id
        RecordManagementService(self.env).unlink_record(rp)
        self.assertFalse(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_unlink_record_best_effort_on_blocked_delete(self):
        rp = self._rental_property()
        rp_id = rp.id
        with patch.object(type(rp), "unlink", side_effect=Exception("blocked")):
            # Must not raise.
            RecordManagementService(self.env).unlink_record(rp)
        self.assertTrue(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_unlink_record_keeps_transaction_usable_after_blocked_delete(self):
        """A blocked delete is a foreign-key violation, which aborts the whole
        transaction. The savepoint inside unlink_record is what lets the caller
        carry on afterwards — without it the caller's remaining work (further
        unlinks, the chatter note) dies on InFailedSqlTransaction and the change
        the user just confirmed is rolled back."""
        rp = self._rental_property()

        def abort_transaction(*args, **kwargs):
            # Any failing statement puts the transaction in the aborted state a
            # real FK violation would.
            self.env.cr.execute("SELECT 1 / 0")

        with patch.object(type(rp), "unlink", side_effect=abort_transaction):
            RecordManagementService(self.env).unlink_record(rp)

        # The caller must still be able to touch the database.
        follow_up = self._rental_property()
        self.assertTrue(follow_up.exists())

    def test_unlink_record_noop_on_empty(self):
        empty = self.env["maintenance.rental.property"].browse(False)
        RecordManagementService(self.env).unlink_record(empty)  # must not raise


@tagged("onecore")
class TestRemoveRentalObject(TransactionCase):
    """MIM-1840: the Objektsinformation trashcan. Object-only — the contract and
    tenant are deliberately left alone."""

    def setUp(self):
        super().setUp()
        self.service = RecordManagementService(self.env)

    def _request_with_tenant(self, **kwargs):
        request = create_maintenance_request(self.env, **kwargs)
        lease = create_lease(self.env, maintenance_request_id=request.id)
        tenant = create_tenant(self.env, maintenance_request_id=request.id)
        request.write({"lease_id": lease.id, "tenant_id": tenant.id})
        return request

    def test_removes_rental_property_and_unlinks_it(self):
        request = self._request_with_tenant(space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        request.write({"rental_property_id": rp.id})
        rp_id = rp.id

        self.service.remove_rental_object(request)

        self.assertFalse(request.rental_property_id)
        self.assertFalse(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_removes_parking_space(self):
        request = self._request_with_tenant(space_caption="Bilplats")
        ps = create_parking_space(self.env, maintenance_request_id=request.id)
        request.write({"parking_space_id": ps.id})
        ps_id = ps.id

        self.service.remove_rental_object(request)

        self.assertFalse(request.parking_space_id)
        self.assertFalse(self.env["maintenance.parking.space"].browse(ps_id).exists())

    def test_removes_facility(self):
        request = self._request_with_tenant(space_caption="Lokal")
        facility = create_facility(self.env, maintenance_request_id=request.id)
        request.write({"facility_id": facility.id})
        facility_id = facility.id

        self.service.remove_rental_object(request)

        self.assertFalse(request.facility_id)
        self.assertFalse(self.env["maintenance.facility"].browse(facility_id).exists())

    def test_leaves_lease_and_tenant_untouched(self):
        """Explicit product decision: the object trash is object-only, even though
        that leaves a contract/tenant with no object."""
        request = self._request_with_tenant(space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        request.write({"rental_property_id": rp.id})
        lease_id, tenant_id = request.lease_id.id, request.tenant_id.id

        self.service.remove_rental_object(request)

        self.assertEqual(request.lease_id.id, lease_id)
        self.assertEqual(request.tenant_id.id, tenant_id)
        self.assertTrue(self.env["maintenance.lease"].browse(lease_id).exists())
        self.assertTrue(self.env["maintenance.tenant"].browse(tenant_id).exists())

    def test_clears_field_even_when_unlink_is_blocked(self):
        request = self._request_with_tenant(space_caption="Lägenhet")
        rp = create_rental_property(self.env, maintenance_request_id=request.id)
        request.write({"rental_property_id": rp.id})

        with patch.object(type(rp), "unlink", side_effect=Exception("blocked")):
            self.service.remove_rental_object(request)

        self.assertFalse(request.rental_property_id)

    def test_noop_when_no_object_attached(self):
        request = self._request_with_tenant(space_caption="Lägenhet")
        self.service.remove_rental_object(request)  # must not raise
        self.assertFalse(request.rental_property_id)


@tagged("onecore")
class TestRemoveTenant(TransactionCase):
    """MIM-1840: the Hyresgäst trashcan. Tenant and contract are one unit — the
    section header sits above both, so its trash vacates the whole section."""

    def setUp(self):
        super().setUp()
        self.service = RecordManagementService(self.env)

    def _request_with_everything(self):
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
        return request

    def test_clears_and_unlinks_both_tenant_and_lease(self):
        request = self._request_with_everything()
        lease_id, tenant_id = request.lease_id.id, request.tenant_id.id

        self.service.remove_tenant(request)

        self.assertFalse(request.lease_id)
        self.assertFalse(request.tenant_id)
        self.assertFalse(self.env["maintenance.lease"].browse(lease_id).exists())
        self.assertFalse(self.env["maintenance.tenant"].browse(tenant_id).exists())

    def test_marks_request_manually_vacated(self):
        request = self._request_with_everything()
        self.service.remove_tenant(request)
        self.assertTrue(request.manually_vacated)

    def test_leaves_rental_object_untouched(self):
        request = self._request_with_everything()
        rp_id = request.rental_property_id.id

        self.service.remove_tenant(request)

        self.assertEqual(request.rental_property_id.id, rp_id)
        self.assertTrue(self.env["maintenance.rental.property"].browse(rp_id).exists())

    def test_vacated_request_is_not_auto_refetched(self):
        """manually_vacated is what stops the empty-tenant auto-refetch from
        silently re-populating the tenant we just removed."""
        request = self._request_with_everything()
        self.service.remove_tenant(request)

        with patch.object(
            RecordManagementService, "_create_missing_lease_and_tenant"
        ) as refetch:
            self.service.handle_empty_tenant_logic(request)

        refetch.assert_not_called()

    def test_clears_fields_even_when_unlink_is_blocked(self):
        request = self._request_with_everything()
        lease = request.lease_id

        with patch.object(type(lease), "unlink", side_effect=Exception("blocked")):
            self.service.remove_tenant(request)

        self.assertFalse(request.lease_id)
        self.assertFalse(request.tenant_id)

    def test_noop_when_nothing_attached(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.service.remove_tenant(request)  # must not raise
        self.assertFalse(request.tenant_id)


@tagged("onecore")
class TestRemoveActionPermissions(TransactionCase):
    """A button's groups/invisible only hides the control — a crafted RPC still
    reaches the method, and the method unlinks. So the guard is server-side."""

    def _request(self):
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
        return request

    def test_manager_may_remove_rental_object(self):
        request = self._request()
        manager = create_internal_user(self.env)

        action = request.with_user(manager).action_remove_rental_object()

        self.assertEqual(action, SOFT_RELOAD)
        self.assertFalse(request.rental_property_id)

    def test_manager_may_remove_tenant(self):
        request = self._request()
        manager = create_internal_user(self.env)

        action = request.with_user(manager).action_remove_tenant()

        self.assertEqual(action, SOFT_RELOAD)
        self.assertFalse(request.tenant_id)
        self.assertFalse(request.lease_id)

    def test_external_contractor_may_not_remove_rental_object(self):
        request = self._request()
        contractor = create_external_contractor_user(self.env)

        with self.assertRaises(AccessError):
            request.with_user(contractor).action_remove_rental_object()

        self.assertTrue(request.rental_property_id)

    def test_external_contractor_may_not_remove_tenant(self):
        request = self._request()
        contractor = create_external_contractor_user(self.env)

        with self.assertRaises(AccessError):
            request.with_user(contractor).action_remove_tenant()

        self.assertTrue(request.tenant_id)
        self.assertTrue(request.lease_id)

    def test_non_manager_may_not_remove_rental_object(self):
        request = self._request()
        plain = create_internal_user(self.env)
        plain.group_ids = [(3, self.env.ref("maintenance.group_equipment_manager").id)]

        with self.assertRaises(AccessError):
            request.with_user(plain).action_remove_rental_object()

        self.assertTrue(request.rental_property_id)
