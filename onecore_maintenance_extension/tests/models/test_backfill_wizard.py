from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged
from odoo.exceptions import UserError

from ..utils.test_utils import create_maintenance_request

RESIDENCE = {
    "rentalInformation": {"rentalId": "123-456-789"},
    "name": "Testgatan 1",
    "code": "RES-001",
    "type": {"name": "Lägenhet"},
    "areaSize": 65,
    "entrance": "A",
    "accessibility": {"elevator": True},
    "property": {"code": "P-1", "name": "Fastigheten"},
    "building": {"code": "B-1", "name": "Byggnaden"},
}

RESIDENCE2 = {
    "rentalInformation": {"rentalId": "999-888-777"},
    "name": "Andra vägen 5",
    "code": "RES-002",
    "type": {"name": "Lägenhet"},
    "areaSize": 72,
    "entrance": "B",
    "accessibility": {"elevator": False},
    "property": {"code": "P-2", "name": "Andra fastigheten"},
    "building": {"code": "B-2", "name": "Andra byggnaden"},
}

CONTACT_LEASES_OTHER = [
    {
        "leaseId": "700-111-22-3333/01",
        "leaseNumber": "01",
        "type": "Bostadskontrakt",
        "status": "Current",
        "leaseStartDate": "2023-05-01",
        "lastDebitDate": False,
        "contractDate": "2023-04-01",
        "approvalDate": "2023-04-10",
        "tenants": [
            {
                "contactCode": "P000999",
                "contactKey": "K9",
                "firstName": "Bengt",
                "lastName": "Bengtsson",
                "nationalRegistrationNumber": "196002026789",
                "emailAddress": "bengt@example.com",
                "phoneNumbers": [{"phoneNumber": "0730000000", "isMainNumber": 1}],
                "isTenant": True,
                "specialAttention": False,
            }
        ],
    }
]

CONTACT_LEASES = [
    {
        "leaseId": "406-028-02-0101/08",
        "leaseNumber": "08",
        "type": "Bostadskontrakt",
        "status": "Current",
        "leaseStartDate": "2024-10-01",
        "lastDebitDate": False,
        "contractDate": "2024-09-01",
        "approvalDate": "2024-09-15",
        "tenants": [
            {
                "contactCode": "P123456",
                "contactKey": "K1",
                "firstName": "Anna",
                "lastName": "Andersson",
                "nationalRegistrationNumber": "199001011234",
                "emailAddress": "anna@example.com",
                "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
                "isTenant": True,
                "specialAttention": False,
            }
        ]
    }
]

# A contact holding two contracts (one current, one ended) for the picker test.
_TENANT_MULTI = {
    "contactCode": "P123456",
    "contactKey": "K1",
    "firstName": "Anna",
    "lastName": "Andersson",
    "nationalRegistrationNumber": "199001011234",
    "emailAddress": "anna@example.com",
    "phoneNumbers": [{"phoneNumber": "0700000000", "isMainNumber": 1}],
    "isTenant": True,
    "specialAttention": False,
}

CONTACT_LEASES_MULTI = [
    {
        "leaseId": "406-CURRENT",
        "leaseNumber": "08",
        "type": "Bostadskontrakt",
        "status": "Current",
        "leaseStartDate": "2024-10-01",
        "lastDebitDate": False,
        "contractDate": "2024-09-01",
        "approvalDate": "2024-09-15",
        "tenants": [_TENANT_MULTI],
    },
    {
        "leaseId": "555-ENDED",
        "leaseNumber": "03",
        "type": "Bostadskontrakt",
        "status": "Ended",
        "leaseStartDate": "2018-01-01",
        "lastDebitDate": "2020-01-01",
        "contractDate": "2017-12-01",
        "approvalDate": "2017-12-10",
        "tenants": [_TENANT_MULTI],
    },
]


@tagged("onecore")
class TestBackfillWizard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.fake_api = MagicMock()
        self.fake_api.fetch_residence.return_value = RESIDENCE
        self.fake_api.fetch_contact_leases.return_value = CONTACT_LEASES

    def _wizard(self, request, kind):
        wiz = self.env["maintenance.backfill.wizard"].create(
            {"maintenance_request_id": request.id, "lookup_kind": kind}
        )
        return wiz

    def test_object_search_then_confirm_persists(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "123-456-789"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertEqual(wiz.state, "preview")
            self.assertIn("Testgatan 1", wiz.preview_text)
            result = wiz.action_confirm()

        # Confirm closes the dialog AND reloads the parent form so the newly
        # materialized object shows without a manual page refresh.
        self.assertEqual(result, {"type": "ir.actions.client", "tag": "soft_reload"})
        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.rental_property_id)
        self.assertEqual(reloaded.rental_property_id.rental_property_id, "123-456-789")
        # Independence: object confirm did not create a tenant.
        self.assertFalse(reloaded.tenant_id)

    def test_tenant_search_then_confirm_persists(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "P123456"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            self.assertEqual(wiz.state, "preview")
            self.assertIn("P123456", wiz.preview_text)
            # The contract picker defaults to the contact's active contract.
            self.assertTrue(wiz.lease_option_id)
            result = wiz.action_confirm()

        self.assertEqual(result, {"type": "ir.actions.client", "tag": "soft_reload"})
        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.tenant_id)
        self.assertEqual(reloaded.contact_code, "P123456")
        # The contact's active contract is attached (unlocks the tenant block).
        self.assertTrue(reloaded.lease_id)
        self.assertTrue(reloaded.lease_name)
        # Independence: tenant confirm did not create a rental object.
        self.assertFalse(reloaded.rental_property_id)

    def test_tenant_pick_specific_contract(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.fake_api.fetch_contact_leases.return_value = CONTACT_LEASES_MULTI
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "P123456"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            wiz.action_search()
            options = self.env["maintenance.lease.option"].search(
                [("user_id", "=", self.env.uid)]
            )
            # Both of the contact's contracts are offered.
            self.assertEqual(len(options), 2)
            # Default selection is the active (Gällande) contract.
            self.assertIn("Gällande", wiz.lease_option_id.name)
            # The user picks the other (ended) contract instead.
            ended = options.filtered(lambda o: "555-ENDED" in o.name)
            self.assertTrue(ended)
            wiz.lease_option_id = ended.id
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.lease_id)
        # The chosen (not the default active) contract was attached.
        self.assertIn("555-ENDED", reloaded.lease_name)

    def test_tenant_replace_deletes_previous(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        # Attach a first tenant.
        self.fake_api.fetch_contact_leases.return_value = CONTACT_LEASES
        wiz1 = self._wizard(request, "tenant")
        wiz1.lookup_value = "P123456"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        first_tenant_id = request.tenant_id.id
        self.assertTrue(first_tenant_id)

        # Change to a different tenant.
        self.fake_api.fetch_contact_leases.return_value = CONTACT_LEASES_OTHER
        wiz2 = self._wizard(request, "tenant")
        wiz2.lookup_value = "P000999"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(reloaded.contact_code, "P000999")
        # The previously linked tenant record was deleted.
        self.assertFalse(
            self.env["maintenance.tenant"].browse(first_tenant_id).exists()
        )

    def test_object_replace_deletes_previous(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.fake_api.fetch_residence.return_value = RESIDENCE
        wiz1 = self._wizard(request, "rental_object")
        wiz1.lookup_value = "123-456-789"
        with patch.object(type(wiz1), "_get_core_api", return_value=self.fake_api):
            wiz1.action_search()
            wiz1.action_confirm()
        first_object_id = request.rental_property_id.id
        self.assertTrue(first_object_id)

        # Change to a different rental object.
        self.fake_api.fetch_residence.return_value = RESIDENCE2
        wiz2 = self._wizard(request, "rental_object")
        wiz2.lookup_value = "999-888-777"
        with patch.object(type(wiz2), "_get_core_api", return_value=self.fake_api):
            wiz2.action_search()
            wiz2.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertEqual(
            reloaded.rental_property_id.rental_property_id, "999-888-777"
        )
        # The previously linked rental-property record was deleted.
        self.assertFalse(
            self.env["maintenance.rental.property"].browse(first_object_id).exists()
        )

    def test_object_not_found_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.fake_api.fetch_residence.return_value = None
        wiz = self._wizard(request, "rental_object")
        wiz.lookup_value = "000"
        with patch.object(type(wiz), "_get_core_api", return_value=self.fake_api):
            with self.assertRaises(UserError):
                wiz.action_search()

    def test_empty_value_raises(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        wiz = self._wizard(request, "tenant")
        wiz.lookup_value = "   "
        with self.assertRaises(UserError):
            wiz.action_search()
