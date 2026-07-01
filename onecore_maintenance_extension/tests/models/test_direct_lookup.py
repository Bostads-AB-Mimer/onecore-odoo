from unittest.mock import MagicMock

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ...models.services.direct_lookup_service import DirectLookupService
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
class TestPopulateRentalObject(TransactionCase):
    def setUp(self):
        super().setUp()
        self.core_api = MagicMock()
        self.service = DirectLookupService(self.env, self.core_api)

    def test_residence_fills_rental_property_option_only(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_residence.return_value = RESIDENCE

        result = self.service.populate_rental_object(request, "123-456-789")

        self.assertIsNone(result)
        self.core_api.fetch_residence.assert_called_once_with("123-456-789")
        option = request.rental_property_option_id
        self.assertTrue(option)
        self.assertEqual(option.code, "RES-001")
        self.assertEqual(option.address, "Testgatan 1")
        self.assertEqual(option.building, "Byggnaden")
        # Strictly independent: tenant is untouched.
        self.assertFalse(request.tenant_option_id)
        self.assertFalse(request.tenant_id)
        self.assertFalse(request.lease_option_id)

    def test_missing_residence_returns_warning(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.core_api.fetch_residence.return_value = None

        result = self.service.populate_rental_object(request, "000")

        self.assertIn("warning", result)
        self.assertEqual(result["warning"]["title"], "Inget hyresobjekt hittades")
        self.assertFalse(request.rental_property_option_id)

    def test_non_rentalid_space_type_is_noop(self):
        request = create_maintenance_request(self.env, space_caption="Byggnad")
        result = self.service.populate_rental_object(request, "whatever")
        self.assertIsNone(result)
        self.core_api.fetch_residence.assert_not_called()
