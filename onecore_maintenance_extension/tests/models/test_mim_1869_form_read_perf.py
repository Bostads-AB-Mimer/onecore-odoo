import time
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import create_maintenance_request, create_rental_property
from ...models import maintenance as maintenance_module

CORE_API_PATH = "odoo.addons.onecore_api.core_api.CoreApi"


def _residence_payload(block_reasons):
    return {
        "propertyObject": {
            "rentalBlocks": [{"blockReason": reason} for reason in block_reasons]
        }
    }


@tagged("onecore")
class TestFloorPlanUrl(TransactionCase):
    """MIM-1869: floor plan is a computed URL, no server-side download."""

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


@tagged("onecore")
class TestRequiresPestControl(TransactionCase):
    """MIM-1869: pest control status is cached per rental id with a TTL."""

    def setUp(self):
        super().setUp()
        maintenance_module._pest_control_cache.clear()
        self.rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201"
        )
        self.request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=self.rental_property.id,
        )

    def _read_pest_control(self, block_reasons=None, side_effect=None):
        with patch(CORE_API_PATH) as MockApi:
            fetch = MockApi.return_value.fetch_residence
            if side_effect:
                fetch.side_effect = side_effect
            else:
                fetch.return_value = _residence_payload(block_reasons or [])
            self.request.invalidate_recordset(["requires_pest_control"])
            value = self.request.requires_pest_control
        return value, fetch

    def test_skadedjur_block_sets_flag(self):
        value, fetch = self._read_pest_control(["SKADEDJUR"])
        self.assertTrue(value)
        fetch.assert_called_once_with("705-022-04-0201", timeout=5)

    def test_other_block_reason_does_not_set_flag(self):
        value, _ = self._read_pest_control(["RENOVERING"])
        self.assertFalse(value)

    def test_no_blocks_does_not_set_flag(self):
        value, _ = self._read_pest_control([])
        self.assertFalse(value)

    def test_result_is_cached_within_ttl(self):
        value, fetch = self._read_pest_control(["SKADEDJUR"])
        self.assertTrue(value)
        with patch(CORE_API_PATH) as MockApi:
            self.request.invalidate_recordset(["requires_pest_control"])
            self.assertTrue(self.request.requires_pest_control)
            MockApi.return_value.fetch_residence.assert_not_called()

    def test_expired_cache_entry_is_refetched(self):
        self._read_pest_control(["SKADEDJUR"])
        maintenance_module._pest_control_cache["705-022-04-0201"] = (
            time.monotonic() - 1,
            True,
        )
        value, fetch = self._read_pest_control([])
        self.assertFalse(value)
        fetch.assert_called_once()

    def test_fetch_error_defaults_to_false_and_is_not_cached(self):
        value, _ = self._read_pest_control(side_effect=Exception("boom"))
        self.assertFalse(value)
        self.assertNotIn("705-022-04-0201", maintenance_module._pest_control_cache)
