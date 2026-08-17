from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError

from ..utils.test_utils import create_maintenance_request

SOFT_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


def _residence(rental_id, code):
    return {
        "rentalInformation": {"rentalId": rental_id},
        "name": f"Gatan {code}",
        "code": code,
        "type": {"name": "4 rum och kök"},
        "areaSize": 96,
        "entrance": "03",
        "accessibility": {"elevator": False},
        "property": {"code": "P-1", "name": "Klädnypan 3"},
        "building": {"code": "B-1", "name": "Byggnaden"},
    }


def _parking(rental_id, code):
    return {
        "parkingSpace": {
            "name": f"P {code}",
            "code": code,
            "parkingSpaceType": {"name": "Parkeringsplats utan el", "code": "PP"},
            "parkingNumber": code,
        },
        "propertyCode": "P-1",
        "propertyName": "Klädnypan 3",
        "address": {
            "streetAddress": "Håkantorpsgatan 117",
            "postalCode": "72340",
            "city": "Västerås",
        },
    }


def _tenant(contact_code, name):
    first, last = name.split(" ", 1)
    return {
        "contactCode": contact_code,
        "contactKey": "K-" + contact_code,
        "firstName": first,
        "lastName": last,
        "nationalRegistrationNumber": "194903073015",
        "emailAddress": "t@example.com",
        "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
        "isTenant": True,
        "specialAttention": False,
    }


def _lease(lease_id, rental_id, lease_type, contact_code, name):
    return {
        "leaseId": lease_id,
        "leaseNumber": lease_id.split("/")[-1],
        "type": lease_type,
        "status": "Current",
        "leaseStartDate": "1977-06-01",
        "lastDebitDate": False,
        "contractDate": "1977-05-01",
        "approvalDate": "1977-05-15",
        "rentalPropertyId": rental_id,
        "tenants": [_tenant(contact_code, name)],
    }


RES_LEASE = _lease(
    "216-034-03-0101/01", "216-034-03-0101", "Bostadskontrakt", "P005468", "Sven Olofsson"
)
PARK_LEASE = _lease(
    "216-704-00-0034/01", "216-704-00-0034", "P-Platskontrakt", "P005468", "Sven Olofsson"
)
OTHER_RES_LEASE = _lease(
    "700-111-22-3333/01", "700-111-22-3333", "Bostadskontrakt", "P000999", "Bengt Bengtsson"
)

RESIDENCE = _residence("216-034-03-0101", "RES-001")
OTHER_RESIDENCE = _residence("700-111-22-3333", "RES-OTHER")
PARKING = _parking("216-704-00-0034", "0034")

# A co-signed lease: two tenants in payload order (primary first).
CO_SIGNED_LEASE = dict(
    RES_LEASE,
    tenants=[_tenant("P005468", "Sven Olofsson"), _tenant("P009999", "Anna Andersson")],
)
# A contract with no tenants (should never occur in real data, but must be handled).
TENANTLESS_LEASE = dict(OTHER_RES_LEASE, tenants=[])


@tagged("onecore")
class TestBackfillWizard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake_api = MagicMock()

    def _wizard(self, request, kind):
        return self.env["maintenance.backfill.wizard"].create(
            {"maintenance_request_id": request.id, "lookup_kind": kind}
        )

    def _onecore_returns(self, leases, residence=None, parking=None):
        """Stub the two calls a lookup makes: the leases, then their object."""
        self.fake_api.fetch_leases_unfiltered.return_value = leases
        self.fake_api.fetch_residence.return_value = residence
        self.fake_api.fetch_parking_space.return_value = parking

    def _lease_options(self):
        return self.env["maintenance.lease.option"].search(
            [("user_id", "=", self.env.uid)]
        )

    def test_object_lookup_attaches_object_lease_tenant(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertTrue(wiz.lease_option_id)
            self.assertFalse(wiz.is_vacant)  # a contract was found
            result = wiz.action_confirm()

        self.assertEqual(result, SOFT_RELOAD)
        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertTrue(reloaded.lease_id)
        self.assertEqual(reloaded.contact_code, "P005468")

    def test_tenant_lookup_attaches_object_lease_tenant(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "P005468"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertTrue(wiz.lease_option_id)
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertTrue(reloaded.lease_id)
        self.assertEqual(reloaded.contact_code, "P005468")
        self.assertEqual(reloaded.space_caption, "Lägenhet")

    def test_vacant_object_attaches_object_only(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([], residence=RESIDENCE)
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertFalse(wiz.lease_option_id)
            self.assertTrue(wiz.is_vacant)  # flagged for the wizard banner
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertFalse(reloaded.tenant_id)

    def test_vacant_object_over_contract_clears_stale_lease_tenant(self):
        # Regression: attaching a vacant object on top of an existing contract must
        # not leave the old lease + tenant dangling (they mismatch the new object).
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz1 = self._wizard(request, "rental_object")
        wiz1.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        old_lease_id = request.lease_id.id
        old_tenant_id = request.tenant_id.id
        self.assertTrue(old_lease_id)
        self.assertTrue(old_tenant_id)

        self._onecore_returns([], residence=RESIDENCE)
        wiz2 = self._wizard(request, "rental_object")
        wiz2.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            self.assertFalse(wiz2.lease_option_id)
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertFalse(reloaded.lease_id)
        self.assertFalse(reloaded.tenant_id)
        self.assertTrue(reloaded.manually_vacated)
        self.assertFalse(self.env["maintenance.lease"].browse(old_lease_id).exists())
        self.assertFalse(self.env["maintenance.tenant"].browse(old_tenant_id).exists())

    def test_blocked_unlink_does_not_roll_back_the_attach(self):
        # Deleting a replaced record can be blocked at the DB level (a foreign key
        # still referencing it). That aborts the transaction, so merely logging the
        # error is not enough: the rest of the confirm — reconciling the remaining
        # records and posting the chatter note — must still go through.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz1 = self._wizard(request, "rental_object")
        wiz1.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        self.assertTrue(request.lease_id)

        def _blocked_unlink(*args, **kwargs):
            # Fails the way a foreign-key violation does: the statement errors and
            # leaves the transaction aborted.
            self.env.cr.execute("SELECT id FROM maintenance_lease WHERE id = 'x'")

        self._onecore_returns([], residence=RESIDENCE)
        wiz2 = self._wizard(request, "rental_object")
        wiz2.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            with patch.object(
                type(self.env["maintenance.lease"]),
                "unlink",
                side_effect=_blocked_unlink,
            ):
                wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertFalse(reloaded.lease_id)
        self.assertFalse(reloaded.tenant_id)
        self.assertTrue(reloaded.manually_vacated)

    def test_vacant_object_does_not_refetch_on_render(self):
        # Regression: a deliberately vacant object must not trigger the empty-tenant
        # auto-fetch on every form render (which would re-create the tenant/lease).
        from ...models.services.record_management_service import (
            RecordManagementService,
        )

        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([], residence=RESIDENCE)
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        with patch.object(
            RecordManagementService, "_create_missing_lease_and_tenant"
        ) as refetch:
            _ = reloaded.empty_tenant  # triggers _compute_empty_tenant
            refetch.assert_not_called()

    def test_cosigned_lease_attaches_searched_tenant(self):
        # Regression: searching the co-signer's kundnummer must attach that person,
        # not the lease's primary tenant.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([CO_SIGNED_LEASE], residence=RESIDENCE)
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "P009999"  # the co-signer, not the primary tenant
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertEqual(wiz.prev_tenant_contact, "P009999")
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(reloaded.contact_code, "P009999")

    def test_contract_without_tenant_clears_previous_tenant(self):
        # Regression: switching to a contract that has no tenants must clear the old
        # tenant rather than leaving it attached.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz1 = self._wizard(request, "rental_object")
        wiz1.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        old_tenant_id = request.tenant_id.id
        self.assertTrue(old_tenant_id)

        self._onecore_returns([TENANTLESS_LEASE], residence=OTHER_RESIDENCE)
        wiz2 = self._wizard(request, "rental_object")
        wiz2.lookup_value = "700-111-22-3333"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            self.assertTrue(wiz2.lease_option_id)  # a contract IS attached...
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.lease_id)
        self.assertFalse(reloaded.tenant_id)  # ...but no stale tenant
        self.assertFalse(
            self.env["maintenance.tenant"].browse(old_tenant_id).exists()
        )

    def test_kundnummer_shows_all_types_and_switching_realigns_space(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns(
            [RES_LEASE, PARK_LEASE], residence=RESIDENCE, parking=PARKING
        )

        # First attach the residence contract.
        wiz1 = self._wizard(request, "tenant")
        wiz1.lookup_value = "P005468"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            leases = self._lease_options()
            self.assertEqual(len(leases), 2)  # both types offered
            wiz1.lease_option_id = leases.filtered(
                lambda l: l.rental_property_option_id
            ).id
            wiz1.action_confirm()
        first_object_id = request.rental_property_id.id
        self.assertTrue(first_object_id)
        self.assertEqual(request.space_caption, "Lägenhet")

        # Then switch to the parking contract → space realigns, old object cleared.
        wiz2 = self._wizard(request, "tenant")
        wiz2.lookup_value = "P005468"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            wiz2.lease_option_id = self._lease_options().filtered(
                lambda l: l.parking_space_option_id
            ).id
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(reloaded.space_caption, "Bilplats")
        self.assertTrue(reloaded.parking_space_id)
        self.assertFalse(reloaded.rental_property_id)
        # The replaced residence record was deleted.
        self.assertFalse(
            self.env["maintenance.rental.property"].browse(first_object_id).exists()
        )

    def test_object_lookup_resolves_other_type_and_switches_space(self):
        # Request is a Bilplats, but the pasted objektnummer is a residence: it
        # should resolve as a residence and realign the request to Lägenhet.
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(reloaded.space_caption, "Lägenhet")
        self.assertTrue(reloaded.rental_property_id)
        self.assertFalse(reloaded.parking_space_id)

    def test_replace_deletes_previous(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        wiz1 = self._wizard(request, "rental_object")
        wiz1.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        first_object_id = request.rental_property_id.id
        first_tenant_id = request.tenant_id.id

        self._onecore_returns([OTHER_RES_LEASE], residence=OTHER_RESIDENCE)
        wiz2 = self._wizard(request, "rental_object")
        wiz2.lookup_value = "700-111-22-3333"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(reloaded.contact_code, "P000999")
        self.assertFalse(
            self.env["maintenance.rental.property"].browse(first_object_id).exists()
        )
        self.assertFalse(
            self.env["maintenance.tenant"].browse(first_tenant_id).exists()
        )

    def test_not_found_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.fake_api.fetch_leases_unfiltered.return_value = []
        self.fake_api.fetch_residence.return_value = None
        self.fake_api.fetch_parking_space.return_value = None
        self.fake_api.fetch_facility.return_value = None
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "000"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            with self.assertRaises(UserError) as caught:
                wiz.action_search()
        self.assertIn("Inget hyresobjekt hittades", str(caught.exception))

    def test_failed_lookup_reports_outage_not_wrong_number(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.fake_api.fetch_leases_unfiltered.side_effect = ConnectionError("boom")
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            with self.assertRaises(UserError) as caught:
                wiz.action_search()
        self.assertIn("misslyckades", str(caught.exception))

    def test_attach_posts_one_summary_note(self):
        # The attach writes half a dozen fields; the user should get a single
        # chatter entry for it, not one per write.
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self._onecore_returns([RES_LEASE], residence=RESIDENCE)
        before = len(request.message_ids)
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "216-034-03-0101"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            wiz.action_confirm()

        posted = request.message_ids[: len(request.message_ids) - before]
        self.assertEqual(len(posted), 1)
        body = posted.body
        self.assertIn("Hyresobjekt", body)
        self.assertIn("Hyresgäst", body)

    def test_empty_value_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "   "
        with self.assertRaises(UserError):
            wiz.action_search()
