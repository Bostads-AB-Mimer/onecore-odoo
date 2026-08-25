"""Tests for ManagementAreaService (MIM-1967) — the distrikt (cost center) /
kvartersvärdsområde (kvv area) snapshot on maintenance requests, the team
pairing behind "Tilldela resursgrupp" and the backfill used by the cron.

OneCore is always mocked (patch CoreApi); ``onecore_base_url`` is only set in
tests that expect a call, because the service refuses to construct the client
without it.
"""
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import (
    create_building,
    create_facility,
    create_internal_user,
    create_maintenance_request,
    create_parking_space,
    create_property,
    create_rental_property,
    create_rental_property_option,
)
from ....models.services import management_area_service as mas_module
from ....models.services.management_area_service import ManagementAreaService

CORE_API_PATH = "odoo.addons.onecore_api.core_api.CoreApi"


def kvv_payload(
    kvv_code="61141",
    kvv_name="Distrikt Väst: BÄCKBY",
    cc_code="61140",
    cc_name="Distrikt Väst",
):
    """Shape of GET /properties/{code}/kvv-area ``content``."""
    return {
        "kvvArea": {"id": 41, "code": kvv_code, "name": kvv_name},
        "costCenter": {"id": 4, "code": cc_code, "name": cc_name},
        "responsible": None,
    }


class ManagementAreaTestMixin:
    """Helpers shared with the model-level tests."""

    def setUp(self):
        super().setUp()
        # Module-level per-worker cache: without this a lookup cached by an
        # earlier test would make the next one see zero API calls.
        mas_module._district_cache.clear()

    def _configure_onecore(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "onecore_base_url", "https://core.test"
        )

    def _stage(self, name):
        return self.env["maintenance.stage"].search([("name", "=", name)], limit=1)

    def _apartment_request(self, estate_code="2201", **kwargs):
        """Lägenhet request whose rental property carries ``estate_code``.
        Created while OneCore is unconfigured unless the caller patched it."""
        rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201", estate_code=estate_code
        )
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=rental_property.id,
            **kwargs,
        )
        # create() returns a recordset carrying creating_records=True, which
        # makes later writes skip chatter tracking. Re-browse to get the same
        # behaviour as the web client (fresh env per request).
        return self.env["maintenance.request"].browse(request.id)

    def _set_district(self, request, cc_code="61140", cc_name="Distrikt Väst"):
        request.sudo().write(
            {"cost_center_code": cc_code, "cost_center_name": cc_name}
        )


@tagged("onecore")
class TestManagementAreaService(ManagementAreaTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self.service = ManagementAreaService(self.env)
        self.vast_team = self.env.ref("onecore_maintenance_extension.2")
        self.vast_team.cost_center_code = "61140"

    # ------------------------------------------------------------------
    # Property code chain
    # ------------------------------------------------------------------
    def test_property_code_from_rental_property(self):
        request = self._apartment_request(estate_code="2201")
        self.assertEqual(self.service.get_property_code(request), "2201")

    def test_property_code_from_parking_space(self):
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        parking = create_parking_space(
            self.env, maintenance_request_id=request.id, property_code="3301"
        )
        request.parking_space_id = parking.id
        self.assertEqual(self.service.get_property_code(request), "3301")

    def test_property_code_from_facility(self):
        request = create_maintenance_request(self.env, space_caption="Lokal")
        facility = create_facility(
            self.env, maintenance_request_id=request.id, property_code="4401"
        )
        request.facility_id = facility.id
        self.assertEqual(self.service.get_property_code(request), "4401")

    def test_property_code_from_property(self):
        request = create_maintenance_request(self.env, space_caption="Fastighet")
        prop = create_property(self.env, maintenance_request_id=request.id, code="5501")
        request.property_id = prop.id
        self.assertEqual(self.service.get_property_code(request), "5501")

    def test_property_code_from_building(self):
        request = create_maintenance_request(self.env, space_caption="Byggnad")
        building = create_building(
            self.env, maintenance_request_id=request.id, property_code="6601"
        )
        request.building_id = building.id
        self.assertEqual(self.service.get_property_code(request), "6601")

    def test_property_code_missing(self):
        request = create_maintenance_request(self.env)
        self.assertFalse(self.service.get_property_code(request))

    # ------------------------------------------------------------------
    # fetch_for_property
    # ------------------------------------------------------------------
    def test_fetch_skips_when_onecore_not_configured(self):
        with patch(CORE_API_PATH) as MockApi:
            ok, values = self.service.fetch_for_property("2201")
        self.assertFalse(ok)
        self.assertIsNone(values)
        MockApi.assert_not_called()

    def test_fetch_skips_without_property_code(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            ok, values = self.service.fetch_for_property(False)
        self.assertFalse(ok)
        self.assertIsNone(values)
        MockApi.assert_not_called()

    def test_fetch_normalizes_payload(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            ok, values = self.service.fetch_for_property("2201")
            fetch = MockApi.return_value.fetch_kvv_area_for_property
        fetch.assert_called_once_with("2201", timeout=5)
        self.assertTrue(ok)
        self.assertEqual(
            values,
            {
                "kvv_area_code": "61141",
                "kvv_area_name": "Distrikt Väst: BÄCKBY",
                "cost_center_code": "61140",
                "cost_center_name": "Distrikt Väst",
            },
        )

    def test_fetch_missing_kvv_name_becomes_false(self):
        """OneCore has no kvv-area names yet — must not break normalisation."""
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload(
                kvv_name=None
            )
            ok, values = self.service.fetch_for_property("2201")
        self.assertTrue(ok)
        self.assertEqual(values["kvv_area_code"], "61141")
        self.assertFalse(values["kvv_area_name"])

    def test_fetch_unlinked_property_is_ok_without_values(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = None
            ok, values = self.service.fetch_for_property("2201")
        self.assertTrue(ok)
        self.assertIsNone(values)

    def test_fetch_error_is_not_ok(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.side_effect = Exception(
                "boom"
            )
            ok, values = self.service.fetch_for_property("2201")
        self.assertFalse(ok)
        self.assertIsNone(values)

    def test_fetch_is_cached_per_property(self):
        """Second lookup of the same property makes no call (form preview +
        create() share one)."""
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.fetch_for_property("2201")
            ok, values = self.service.fetch_for_property("2201")
            self.assertEqual(
                MockApi.return_value.fetch_kvv_area_for_property.call_count, 1
            )
        self.assertTrue(ok)
        self.assertEqual(values["cost_center_code"], "61140")

    def test_fetch_error_is_not_cached(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            fetch = MockApi.return_value.fetch_kvv_area_for_property
            fetch.side_effect = Exception("boom")
            self.service.fetch_for_property("2201")
            fetch.side_effect = None
            fetch.return_value = kvv_payload()
            ok, values = self.service.fetch_for_property("2201")
        self.assertTrue(ok)
        self.assertEqual(values["cost_center_code"], "61140")

    # ------------------------------------------------------------------
    # Form preview (before save)
    # ------------------------------------------------------------------
    def test_property_code_from_options_before_save(self):
        record = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})
        self.assertFalse(self.service.get_property_code_from_options(record))
        option = create_rental_property_option(self.env, estate_code="2201")
        record.rental_property_option_id = option
        self.assertEqual(self.service.get_property_code_from_options(record), "2201")

    def test_preview_fills_district_before_save(self):
        self._configure_onecore()
        option = create_rental_property_option(self.env, estate_code="2201")
        record = self.env["maintenance.request"].new(
            {"space_caption": "Lägenhet", "rental_property_option_id": option.id}
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.assertTrue(self.service.preview(record))
        self.assertEqual(record.cost_center_name, "Distrikt Väst")
        self.assertEqual(record.kvv_area_code, "61141")
        # MIM-1967: codes are what's shown, not captions
        self.assertEqual(record.kvv_area_display, "61141")
        self.assertEqual(record.cost_center_display, "61140 - Distrikt Väst")

    def test_preview_prefills_empty_team_from_district(self):
        """Resursgrupp is required to save, so the form prefills it — the
        button alone can't help before the request exists."""
        self._configure_onecore()
        option = create_rental_property_option(self.env, estate_code="2201")
        record = self.env["maintenance.request"].new(
            {"space_caption": "Lägenhet", "rental_property_option_id": option.id}
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.preview(record)
        self.assertEqual(record.maintenance_team_id, self.vast_team)

    def test_preview_keeps_team_the_user_already_picked(self):
        """A Vitvaru-/Skadedjursärende must keep its team."""
        self._configure_onecore()
        vitvaror = self.env.ref("onecore_maintenance_extension.1")
        option = create_rental_property_option(self.env, estate_code="2201")
        record = self.env["maintenance.request"].new(
            {
                "space_caption": "Lägenhet",
                "rental_property_option_id": option.id,
                "maintenance_team_id": vitvaror.id,
            }
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.preview(record)
        self.assertEqual(record.maintenance_team_id, vitvaror)
        self.assertEqual(record.cost_center_name, "Distrikt Väst")

    def test_preview_without_matching_team_leaves_team_empty(self):
        self._configure_onecore()
        option = create_rental_property_option(self.env, estate_code="2201")
        record = self.env["maintenance.request"].new(
            {"space_caption": "Lägenhet", "rental_property_option_id": option.id}
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload(
                cc_code="61199", cc_name="Distrikt Okänt"
            )
            self.service.preview(record)
        self.assertFalse(record.maintenance_team_id)
        self.assertEqual(record.cost_center_name, "Distrikt Okänt")

    def test_preview_follows_a_second_property_in_the_same_form(self):
        """Picking another search hit must not keep the first property's
        distrikt — nor the team we prefilled from it."""
        self._configure_onecore()
        record = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})
        record.rental_property_option_id = create_rental_property_option(
            self.env, estate_code="2201"
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.preview(record)
        self.assertEqual(record.cost_center_code, "61140")
        self.assertEqual(record.maintenance_team_id, self.vast_team)

        mitt_team = self.env.ref("onecore_maintenance_extension.5")
        mitt_team.cost_center_code = "61110"
        record.rental_property_option_id = create_rental_property_option(
            self.env, estate_code="3301"
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload(
                kvv_code="61111", cc_code="61110", cc_name="Distrikt Mitt"
            )
            self.service.preview(record)

        self.assertEqual(record.cost_center_name, "Distrikt Mitt")
        self.assertEqual(record.kvv_area_code, "61111")
        self.assertEqual(record.maintenance_team_id, mitt_team, "team följde inte med")

    def test_preview_keeps_manual_team_when_switching_property(self):
        self._configure_onecore()
        vitvaror = self.env.ref("onecore_maintenance_extension.1")
        record = self.env["maintenance.request"].new(
            {
                "space_caption": "Lägenhet",
                "maintenance_team_id": vitvaror.id,
            }
        )
        record.rental_property_option_id = create_rental_property_option(
            self.env, estate_code="2201"
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.preview(record)
        self.assertEqual(record.maintenance_team_id, vitvaror)
        self.assertEqual(record.cost_center_code, "61140")

    def test_preview_skips_when_already_known_or_without_property(self):
        self._configure_onecore()
        empty = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})
        with patch(CORE_API_PATH) as MockApi:
            self.assertFalse(self.service.preview(empty))
            MockApi.assert_not_called()

        # Already carrying what OneCore would answer: nothing to write
        option = create_rental_property_option(self.env, estate_code="2201")
        unchanged = self.env["maintenance.request"].new(
            {
                "space_caption": "Lägenhet",
                "rental_property_option_id": option.id,
                "cost_center_code": "61140",
                "cost_center_name": "Distrikt Väst",
                "kvv_area_code": "61141",
            }
        )
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.assertFalse(self.service.preview(unchanged))
        self.assertEqual(unchanged.cost_center_code, "61140")

    # ------------------------------------------------------------------
    # populate
    # ------------------------------------------------------------------
    def test_populate_writes_snapshot_and_stamp(self):
        request = self._apartment_request()
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.assertTrue(self.service.populate(request))
        self.assertEqual(request.kvv_area_code, "61141")
        self.assertEqual(request.kvv_area_name, "Distrikt Väst: BÄCKBY")
        self.assertEqual(request.cost_center_code, "61140")
        self.assertEqual(request.cost_center_name, "Distrikt Väst")
        self.assertTrue(request.management_area_lookup_at)

    def test_populate_skips_when_already_set(self):
        request = self._apartment_request()
        self._set_district(request)
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            self.assertFalse(self.service.populate(request))
            MockApi.return_value.fetch_kvv_area_for_property.assert_not_called()

    def test_populate_force_refetches(self):
        request = self._apartment_request()
        self._set_district(request, cc_code="61110", cc_name="Distrikt Mitt")
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.assertTrue(self.service.populate(request, force=True))
        self.assertEqual(request.cost_center_code, "61140")

    def test_populate_failed_lookup_does_not_stamp(self):
        """OneCore down: nothing written so the cron retries later."""
        request = self._apartment_request()
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.side_effect = Exception(
                "boom"
            )
            self.assertFalse(self.service.populate(request))
        self.assertFalse(request.cost_center_code)
        self.assertFalse(request.management_area_lookup_at)

    def test_populate_unlinked_property_stamps_without_values(self):
        """A confirmed 'no district' is stamped so it is not retried forever."""
        request = self._apartment_request()
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = None
            self.assertFalse(self.service.populate(request))
        self.assertFalse(request.cost_center_code)
        self.assertTrue(request.management_area_lookup_at)

    def test_populate_without_property_code_does_nothing(self):
        request = create_maintenance_request(self.env)
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            self.assertFalse(self.service.populate(request))
            MockApi.assert_not_called()
        self.assertFalse(request.management_area_lookup_at)

    def test_populate_posts_no_chatter_note(self):
        request = self._apartment_request()
        messages_before = len(request.message_ids)
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            self.service.populate(request)
        self.assertEqual(len(request.message_ids), messages_before)

    # ------------------------------------------------------------------
    # Team pairing
    # ------------------------------------------------------------------
    def test_find_team_for_cost_center(self):
        self.assertEqual(self.service.find_team_for_cost_center("61140"), self.vast_team)
        self.assertFalse(self.service.find_team_for_cost_center("99999"))
        self.assertFalse(self.service.find_team_for_cost_center(False))

    def test_find_team_ignores_archived_teams(self):
        archived = self.env["maintenance.team"].create(
            {"name": "Gammalt distrikt", "cost_center_code": "61199", "active": False}
        )
        self.assertFalse(self.service.find_team_for_cost_center("61199"))
        self.assertTrue(archived.exists())

    def test_assign_team_sets_district_team(self):
        request = self._apartment_request()
        self._set_district(request)
        self.assertNotEqual(request.maintenance_team_id, self.vast_team)

        result = self.service.assign_team(request)

        self.assertEqual(result["team"], self.vast_team)
        self.assertTrue(result["changed"])
        self.assertIsNone(result["error"])
        self.assertEqual(request.maintenance_team_id, self.vast_team)

    def test_assign_team_clears_assignee_outside_team_and_resets_stage(self):
        outsider = create_internal_user(self.env)
        request = self._apartment_request(user_id=outsider.id)
        self.assertEqual(request.stage_id, self._stage("Resurs tilldelad"))
        self._set_district(request)

        self.service.assign_team(request)

        self.assertEqual(request.maintenance_team_id, self.vast_team)
        self.assertFalse(request.user_id)
        self.assertEqual(request.stage_id, self._stage("Väntar på handläggning"))

    def test_assign_team_keeps_assignee_who_is_member(self):
        member = create_internal_user(self.env)
        self.vast_team.member_ids = [(4, member.id)]
        request = self._apartment_request(user_id=member.id)
        self._set_district(request)

        self.service.assign_team(request)

        self.assertEqual(request.maintenance_team_id, self.vast_team)
        self.assertEqual(request.user_id, member)
        self.assertEqual(request.stage_id, self._stage("Resurs tilldelad"))

    def test_assign_team_is_noop_when_already_on_team(self):
        request = self._apartment_request(maintenance_team_id=self.vast_team.id)
        self._set_district(request)
        messages_before = len(request.message_ids)

        result = self.service.assign_team(request)

        self.assertEqual(result["team"], self.vast_team)
        self.assertFalse(result["changed"])
        self.assertIsNone(result["error"])
        self.assertEqual(len(request.message_ids), messages_before)

    def test_assign_team_without_district_reports_error(self):
        request = self._apartment_request()  # OneCore unconfigured -> no lookup
        result = self.service.assign_team(request)
        self.assertFalse(result["team"])
        self.assertFalse(result["changed"])
        self.assertIn("saknar distrikt", result["error"])

    def test_assign_team_fetches_district_lazily(self):
        """Legacy request: the district is looked up on demand, then paired."""
        request = self._apartment_request()
        self.assertFalse(request.cost_center_code)
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            result = self.service.assign_team(request)
        self.assertEqual(result["team"], self.vast_team)
        self.assertEqual(request.cost_center_code, "61140")
        self.assertEqual(request.maintenance_team_id, self.vast_team)

    def test_assign_team_without_matching_team_keeps_fetched_district(self):
        request = self._apartment_request()
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload(
                cc_code="61199", cc_name="Distrikt Okänt"
            )
            result = self.service.assign_team(request)
        self.assertFalse(result["team"])
        self.assertIn("Distrikt Okänt", result["error"])
        # Not raised -> the snapshot survives
        self.assertEqual(request.cost_center_code, "61199")

    # ------------------------------------------------------------------
    # Kvv-area master sync ("Nuvarande kvartersvärd")
    # ------------------------------------------------------------------
    @staticmethod
    def _kvv_area_list():
        return [
            {
                "id": 41,
                "code": "61141",
                "name": "Distrikt Väst: BÄCKBY",
                "costCenter": {"id": 4, "code": "61140", "name": "Distrikt Väst"},
                "responsible": {
                    "id": "abc-123",
                    "firstName": "Kim",
                    "lastName": "Kvartersvärd",
                    "email": "kim@mimer.nu",
                    "mobilePhone": "070-123 45 67",
                },
            },
            {
                "id": 42,
                "code": "61142",
                "name": None,
                "costCenter": {"id": 4, "code": "61140", "name": "Distrikt Väst"},
                "responsible": None,
            },
        ]

    def _sync_with(self, areas):
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_areas.return_value = areas
            return self.service.sync_kvv_areas()

    def test_sync_kvv_areas_creates_updates_and_skips_unchanged(self):
        self._configure_onecore()
        self.assertEqual(self._sync_with(self._kvv_area_list()), 2)

        area = self.env["maintenance.kvv.area"].search([("code", "=", "61141")])
        self.assertEqual(area.responsible_name, "Kim Kvartersvärd")
        self.assertEqual(area.responsible_phone, "070-123 45 67")
        self.assertEqual(area.responsible_keycloak_id, "abc-123")
        self.assertEqual(area.cost_center_code, "61140")
        self.assertEqual(area.display_name, "Distrikt Väst: BÄCKBY")
        stewardless = self.env["maintenance.kvv.area"].search([("code", "=", "61142")])
        self.assertFalse(stewardless.responsible_name)
        self.assertEqual(stewardless.display_name, "61142")

        # Same payload again: nothing rewritten
        self.assertEqual(self._sync_with(self._kvv_area_list()), 0)

        # Steward change (vikarie) flows through on the next sync
        changed = self._kvv_area_list()
        changed[0]["responsible"] = {
            "id": "def-456",
            "firstName": "Vik",
            "lastName": "Arie",
            "email": "vik@mimer.nu",
        }
        self.assertEqual(self._sync_with(changed), 1)
        self.assertEqual(area.responsible_name, "Vik Arie")

    def test_sync_kvv_areas_skips_when_not_configured(self):
        with patch(CORE_API_PATH) as MockApi:
            self.assertEqual(self.service.sync_kvv_areas(), 0)
            MockApi.assert_not_called()

    def test_sync_kvv_areas_survives_api_error(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_areas.side_effect = Exception("boom")
            self.assertEqual(self.service.sync_kvv_areas(), 0)

    # ------------------------------------------------------------------
    # Cost-center master sync ("Distriktschef")
    # ------------------------------------------------------------------
    def _sync_cost_centers_with(self, trees):
        with patch(CORE_API_PATH) as MockApi:
            api = MockApi.return_value
            api.fetch_cost_centers.return_value = [
                {"id": i, "code": tree["code"]} for i, tree in enumerate(trees)
            ]
            api.fetch_cost_center_tree.side_effect = list(trees)
            return self.service.sync_cost_centers()

    def test_sync_cost_centers_stores_lead_and_deputy(self):
        self._configure_onecore()
        trees = [
            {
                "code": "61140",
                "name": "Distrikt Väst",
                "lead": {"firstName": "Mats", "lastName": "Hedlund",
                         "email": "mats@mimer.nu", "mobilePhone": "070-1"},
                "deputy": {"firstName": "Conny", "lastName": "Larsson"},
            },
            # Mimer Student has no deputy at all — grunddata, not an error
            {
                "code": "61150",
                "name": "Mimer Student",
                "lead": {"firstName": "Lo", "lastName": "Student"},
                "deputy": None,
            },
        ]
        self.assertEqual(self._sync_cost_centers_with(trees), 2)

        vast = self.env["maintenance.cost.center"].search([("code", "=", "61140")])
        self.assertEqual(vast.lead_name, "Mats Hedlund")
        self.assertEqual(vast.lead_email, "mats@mimer.nu")
        self.assertEqual(vast.deputy_name, "Conny Larsson")
        self.assertEqual(vast.display_name, "61140 - Distrikt Väst")

        student = self.env["maintenance.cost.center"].search([("code", "=", "61150")])
        self.assertEqual(student.lead_name, "Lo Student")
        self.assertFalse(student.deputy_name)

        # Unchanged payload writes nothing; a new chef does
        self.assertEqual(self._sync_cost_centers_with(trees), 0)
        trees[0]["lead"] = {"firstName": "Ny", "lastName": "Chef"}
        self.assertEqual(self._sync_cost_centers_with(trees), 1)
        self.assertEqual(vast.lead_name, "Ny Chef")

    def test_sync_cost_centers_skips_when_not_configured(self):
        with patch(CORE_API_PATH) as MockApi:
            self.assertEqual(self.service.sync_cost_centers(), 0)
            MockApi.assert_not_called()

    def test_sync_cost_centers_survives_api_error(self):
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_cost_centers.side_effect = Exception("boom")
            self.assertEqual(self.service.sync_cost_centers(), 0)

    # ------------------------------------------------------------------
    # Backfill
    # ------------------------------------------------------------------
    def _mock_trees(self, MockApi):
        api = MockApi.return_value
        api.fetch_cost_centers.return_value = [
            {"id": 4, "code": "61140", "name": "Distrikt Väst"}
        ]
        api.fetch_cost_center_tree.return_value = {
            "id": 4,
            "code": "61140",
            "name": "Distrikt Väst",
            "kvvAreas": [
                {
                    "id": 41,
                    "code": "61141",
                    "name": None,
                    "properties": [{"code": "2201"}, {"code": "2202"}],
                }
            ],
        }
        return api

    def test_backfill_stamps_requests_from_cost_center_trees(self):
        linked_1 = self._apartment_request(estate_code="2201")
        linked_2 = self._apartment_request(estate_code="2201")
        unlinked = self._apartment_request(estate_code="9999")
        no_code = create_maintenance_request(self.env)
        team_before = linked_1.maintenance_team_id
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_trees(MockApi)
            processed = self.service.backfill_batch(limit=500)

        self.assertGreaterEqual(processed, 4)
        api.fetch_cost_center_tree.assert_called_once_with(4)
        api.fetch_kvv_area_for_property.assert_not_called()
        for request in (linked_1, linked_2):
            self.assertEqual(request.cost_center_code, "61140")
            self.assertEqual(request.cost_center_name, "Distrikt Väst")
            self.assertEqual(request.kvv_area_code, "61141")
            self.assertFalse(request.kvv_area_name)
            self.assertTrue(request.management_area_lookup_at)
        for request in (unlinked, no_code):
            self.assertFalse(request.cost_center_code)
            self.assertTrue(request.management_area_lookup_at)
        # Display only: team/resource untouched
        self.assertEqual(linked_1.maintenance_team_id, team_before)

    def test_backfill_does_not_reprocess_stamped_requests(self):
        requests = self._apartment_request(estate_code="2201") | self._apartment_request(
            estate_code="9999"
        )
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            self._mock_trees(MockApi)
            self.service.backfill_batch(limit=500)
            stamps = requests.mapped("management_area_lookup_at")
            self.service.backfill_batch(limit=500)
        self.assertEqual(requests.mapped("management_area_lookup_at"), stamps)
        self.assertFalse(
            self.env["maintenance.request"].search_count(
                [("id", "in", requests.ids), ("management_area_lookup_at", "=", False)]
            )
        )

    def test_backfill_respects_limit(self):
        self._apartment_request(estate_code="2201")
        self._apartment_request(estate_code="2201")
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            self._mock_trees(MockApi)
            self.assertEqual(self.service.backfill_batch(limit=1), 1)

    def test_backfill_skips_when_onecore_not_configured(self):
        request = self._apartment_request(estate_code="2201")
        with patch(CORE_API_PATH) as MockApi:
            self.assertEqual(self.service.backfill_batch(limit=500), 0)
            MockApi.assert_not_called()
        self.assertFalse(request.management_area_lookup_at)

    def test_backfill_stamps_nothing_when_trees_are_empty(self):
        request = self._apartment_request(estate_code="2201")
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_cost_centers.return_value = []
            self.assertEqual(self.service.backfill_batch(limit=500), 0)
        self.assertFalse(request.management_area_lookup_at)

    def test_backfill_stamps_nothing_when_one_tree_is_missing(self):
        """A partial map would stamp the missing district's requests as looked
        up, excluding them from every future run."""
        request = self._apartment_request(estate_code="2201")
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_trees(MockApi)
            api.fetch_cost_centers.return_value = [
                {"id": 4, "code": "61140", "name": "Distrikt Väst"},
                {"id": 5, "code": "61110", "name": "Distrikt Mitt"},
            ]
            api.fetch_cost_center_tree.side_effect = [
                api.fetch_cost_center_tree.return_value,
                None,  # OneCore hiccup on the second district
            ]
            self.assertEqual(self.service.backfill_batch(limit=500), 0)
        self.assertFalse(request.management_area_lookup_at)

    def test_backfill_stamps_nothing_when_onecore_fails(self):
        request = self._apartment_request(estate_code="2201")
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_cost_centers.side_effect = Exception("boom")
            self.assertEqual(self.service.backfill_batch(limit=500), 0)
        self.assertFalse(request.management_area_lookup_at)
