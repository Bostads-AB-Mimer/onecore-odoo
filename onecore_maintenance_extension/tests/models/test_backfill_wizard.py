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

CONTACT_LEASES = [
    {
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
            wiz.action_confirm()

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
            wiz.action_confirm()

        reloaded = self.env["maintenance.request"].browse(request.id)
        reloaded.invalidate_recordset()
        self.assertTrue(reloaded.tenant_id)
        self.assertEqual(reloaded.contact_code, "P123456")
        # Independence: tenant confirm did not create a rental object.
        self.assertFalse(reloaded.rental_property_id)

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
