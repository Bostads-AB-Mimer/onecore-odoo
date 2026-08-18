from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import create_maintenance_request, create_rental_property


@tagged("onecore")
class TestFloorPlanUrl(TransactionCase):
    """Floor plan is a computed URL, no server-side download."""

    def test_lagenhet_with_rental_property_gets_url(self):
        rental_property = create_rental_property(self.env, name="705-022-04-0201")
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=rental_property.id,
        )
        self.assertEqual(
            request.floor_plan_image_url,
            "https://pub.mimer.nu/bofaktablad/bofaktablad/705-022-04-0201.jpg",
        )

    def test_non_lagenhet_has_no_url(self):
        rental_property = create_rental_property(self.env, name="705-022-04-0201")
        request = create_maintenance_request(
            self.env,
            space_caption="Tvättstuga",
            rental_property_id=rental_property.id,
        )
        self.assertFalse(request.floor_plan_image_url)

    def test_no_rental_property_has_no_url(self):
        request = create_maintenance_request(self.env, space_caption="Lägenhet")
        self.assertFalse(request.floor_plan_image_url)

    def test_compute_makes_no_http_call(self):
        rental_property = create_rental_property(self.env, name="705-022-04-0201")
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=rental_property.id,
        )
        with patch("requests.get") as mock_get, patch("requests.request") as mock_request:
            request.invalidate_recordset(["floor_plan_image_url"])
            request.floor_plan_image_url
            mock_get.assert_not_called()
            mock_request.assert_not_called()
