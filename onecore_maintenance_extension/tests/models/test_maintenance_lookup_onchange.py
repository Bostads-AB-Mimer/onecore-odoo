from unittest.mock import MagicMock, patch

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

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


@tagged("onecore")
class TestLookupOnchange(TransactionCase):
    def setUp(self):
        super().setUp()
        self.request = create_maintenance_request(self.env, space_caption="Lägenhet")

    def test_onchange_rental_object_lookup_populates_and_clears(self):
        fake_api = MagicMock()
        fake_api.fetch_residence.return_value = RESIDENCE
        with patch.object(
            type(self.request), "get_core_api", return_value=fake_api
        ):
            self.request.rental_object_lookup = "123-456-789"
            self.request._onchange_rental_object_lookup()

        self.assertEqual(self.request.rental_property_option_id.code, "RES-001")
        # The transient input is reset after the fetch.
        self.assertFalse(self.request.rental_object_lookup)

    def test_onchange_rental_object_lookup_returns_warning_when_missing(self):
        fake_api = MagicMock()
        fake_api.fetch_residence.return_value = None
        with patch.object(
            type(self.request), "get_core_api", return_value=fake_api
        ):
            self.request.rental_object_lookup = "000"
            result = self.request._onchange_rental_object_lookup()

        self.assertIn("warning", result)
        self.assertFalse(self.request.rental_property_option_id)

    def test_onchange_tenant_lookup_empty_is_noop(self):
        fake_api = MagicMock()
        with patch.object(
            type(self.request), "get_core_api", return_value=fake_api
        ):
            self.request.tenant_lookup = "   "
            result = self.request._onchange_tenant_lookup()

        self.assertIsNone(result)
        fake_api.fetch_contact_leases.assert_not_called()
