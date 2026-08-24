"""Model-level tests for MIM-1967 — "Tillhör distrikt" on maintenance requests
and the "Tilldela resursgrupp" button.

Covers the create() snapshot, the button action (notifications, contractor
guard), the team seed, the cron record and the open_time_report refactor.
"""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..utils.test_utils import (
    create_building,
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
    create_rental_property,
    create_rental_property_option,
)
from .services.test_management_area_service import (
    CORE_API_PATH,
    ManagementAreaTestMixin,
    kvv_payload,
)


@tagged("onecore")
class TestMaintenanceDistrict(ManagementAreaTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self.vast_team = self.env.ref("onecore_maintenance_extension.2")
        self.vast_team.cost_center_code = "61140"
        # The default test user (root) is in group_external_contractor (see
        # security/maintenance.xml), so the button must run as a real
        # internal user or its contractor guard fires.
        self.internal_user = create_internal_user(self.env)

    def _click_assign(self, request):
        return request.with_user(self.internal_user).action_assign_district_team()

    # ------------------------------------------------------------------
    # create()
    # ------------------------------------------------------------------
    def test_create_snapshots_district_from_onecore(self):
        rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201", estate_code="2201"
        )
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            request = create_maintenance_request(
                self.env,
                space_caption="Lägenhet",
                rental_property_id=rental_property.id,
            )
            fetch = MockApi.return_value.fetch_kvv_area_for_property

        fetch.assert_called_once_with("2201", timeout=5)
        self.assertEqual(request.cost_center_name, "Distrikt Väst")
        self.assertEqual(request.cost_center_code, "61140")
        self.assertEqual(request.kvv_area_code, "61141")
        self.assertTrue(request.management_area_lookup_at)
        # Snapshot is silent in the chatter
        self.assertFalse(
            request.message_ids.filtered(
                lambda m: "distrikt" in (m.body or "").lower()
            )
        )

    def test_create_keeps_values_stamped_by_caller(self):
        """core stamps the fields on mimer.nu requests -> no lookup."""
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            request = create_maintenance_request(
                self.env,
                kvv_area_code="61141",
                cost_center_code="61140",
                cost_center_name="Distrikt Väst",
            )
            MockApi.return_value.fetch_kvv_area_for_property.assert_not_called()
        self.assertEqual(request.cost_center_name, "Distrikt Väst")

    def test_create_without_onecore_leaves_fields_empty(self):
        request = self._apartment_request()
        self.assertFalse(request.cost_center_code)
        self.assertFalse(request.cost_center_name)
        self.assertFalse(request.management_area_lookup_at)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def test_onchange_previews_district_before_save(self):
        """Picking a search hit shows the distrikt without saving first."""
        self._configure_onecore()
        option = create_rental_property_option(self.env, estate_code="2201")
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload()
            form = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})
            form.rental_property_option_id = option
            form._onchange_management_area_preview()
        self.assertEqual(form.cost_center_display, "61140 - Distrikt Väst")
        self.assertEqual(form.kvv_area_display, "61141")

    def test_preview_and_create_share_one_api_call(self):
        self._configure_onecore()
        option = create_rental_property_option(self.env, estate_code="2201")
        rental_property = create_rental_property(
            self.env, rental_property_id="705-022-04-0201", estate_code="2201"
        )
        with patch(CORE_API_PATH) as MockApi:
            fetch = MockApi.return_value.fetch_kvv_area_for_property
            fetch.return_value = kvv_payload()
            form = self.env["maintenance.request"].new({"space_caption": "Lägenhet"})
            form.rental_property_option_id = option
            form._onchange_management_area_preview()
            request = create_maintenance_request(
                self.env,
                space_caption="Lägenhet",
                rental_property_id=rental_property.id,
            )
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(request.cost_center_name, "Distrikt Väst")

    def test_current_kvartersvard_resolved_from_master(self):
        """"Nuvarande kvartersvärd" comes from the cron-synced master, never
        from a snapshot on the request."""
        self.env["maintenance.kvv.area"].sudo().create(
            {
                "code": "61141",
                "name": "Distrikt Väst: BÄCKBY",
                "responsible_name": "Kim Kvartersvärd",
            }
        )
        request = self._apartment_request()
        request.sudo().write({"kvv_area_code": "61141"})
        self.assertEqual(request.kvv_area_responsible, "Kim Kvartersvärd")

        # Area known in OneCore terms but not in the master (or no steward) -> dash
        request.sudo().write({"kvv_area_code": "99999"})
        self.assertEqual(request.kvv_area_responsible, "–")

        # No kvv area on the request -> hidden
        request.sudo().write({"kvv_area_code": False})
        self.assertFalse(request.kvv_area_responsible)

    def test_district_manager_formats_and_hides_when_missing(self):
        """Escalation step 3, resolved from the cost-center master."""
        district = self.env["maintenance.cost.center"].sudo().create(
            {"code": "61140", "name": "Distrikt Väst"}
        )
        request = self._apartment_request()
        self._set_district(request)

        # No chef yet -> empty, so the view hides the row
        self.assertFalse(request.district_manager)

        district.write({"lead_name": "Mats Hedlund"})
        request.invalidate_recordset(["district_manager"])
        self.assertEqual(request.district_manager, "Mats Hedlund")

        district.write({"deputy_name": "Conny Larsson"})
        request.invalidate_recordset(["district_manager"])
        self.assertEqual(request.district_manager, "Mats Hedlund (bitr. Conny Larsson)")

        # onecore's test data points both roles at the same person (61120)
        district.write({"deputy_name": "Mats Hedlund"})
        request.invalidate_recordset(["district_manager"])
        self.assertEqual(request.district_manager, "Mats Hedlund")

        district.write({"lead_name": False, "deputy_name": "Conny Larsson"})
        request.invalidate_recordset(["district_manager"])
        self.assertEqual(request.district_manager, "Conny Larsson (bitr.)")

        # District not in the master -> nothing to resolve
        request.sudo().write({"cost_center_code": "99999"})
        self.assertFalse(request.district_manager)

    def test_display_fields_show_codes(self):
        """MIM-1967 (PO): the code is what's rendered — captions are not unique
        and grouping already runs on the code."""
        request = self._apartment_request()
        request.sudo().write(
            {
                "kvv_area_code": "61112",
                "kvv_area_name": "Distrikt Mitt: MALMABERG, SKILJEBO",
                "cost_center_code": "61110",
                "cost_center_name": "Distrikt Mitt",
            }
        )
        self.assertEqual(request.kvv_area_display, "61112")
        # Same format as property-tree's dropdown
        self.assertEqual(request.cost_center_display, "61110 - Distrikt Mitt")

        # Fallbacks: name only if the code is missing, name alone if no code
        request.sudo().write({"kvv_area_code": False})
        self.assertEqual(request.kvv_area_display, "Distrikt Mitt: MALMABERG, SKILJEBO")
        request.sudo().write({"cost_center_code": False})
        self.assertEqual(request.cost_center_display, "Distrikt Mitt")

    # ------------------------------------------------------------------
    # Button
    # ------------------------------------------------------------------
    def test_action_assigns_team_and_notifies(self):
        request = self._apartment_request()
        self._set_district(request)

        action = self._click_assign(request)

        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(action["params"]["type"], "success")
        self.assertIn("Distrikt Väst", action["params"]["message"])
        self.assertEqual(request.maintenance_team_id, self.vast_team)
        # FieldChangeTracker logs the team change
        self.assertTrue(
            request.message_ids.filtered(lambda m: "Distrikt Väst" in (m.body or ""))
        )

    def test_action_always_reloads_the_form(self):
        """Every outcome must chain act_window_close, otherwise the form keeps
        showing the old team/resurs/steg until the user reloads by hand."""
        # 1. team changed
        changed = self._apartment_request()
        self._set_district(changed)
        # 2. already on the district team
        unchanged = self._apartment_request(maintenance_team_id=self.vast_team.id)
        self._set_district(unchanged)
        # 3. warning: district exists but no team carries that cost center
        warning = self._apartment_request()
        self._set_district(warning, cc_code="61199", cc_name="Distrikt Okänt")

        expected = {"type": "ir.actions.act_window_close"}
        for request, outcome in (
            (changed, "success"),
            (unchanged, "info"),
            (warning, "warning"),
        ):
            action = self._click_assign(request)
            self.assertEqual(action["params"]["type"], outcome)
            self.assertEqual(action["params"].get("next"), expected, outcome)

    def test_action_info_when_already_on_team(self):
        request = self._apartment_request(maintenance_team_id=self.vast_team.id)
        self._set_district(request)
        action = self._click_assign(request)
        self.assertEqual(action["params"]["type"], "info")

    def test_action_warns_when_no_team_matches_and_keeps_district(self):
        request = self._apartment_request()
        self._configure_onecore()
        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_kvv_area_for_property.return_value = kvv_payload(
                cc_code="61199", cc_name="Distrikt Okänt"
            )
            action = self._click_assign(request)
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("Ingen resursgrupp", action["params"]["message"])
        self.assertEqual(request.cost_center_name, "Distrikt Okänt")

    def test_action_warns_when_district_unknown(self):
        request = self._apartment_request()  # OneCore unconfigured
        action = self._click_assign(request)
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("saknar distrikt", action["params"]["message"])

    def test_action_blocked_for_external_contractor(self):
        contractor = create_external_contractor_user(self.env)
        contractor_team = self.env["maintenance.team"].create(
            {"name": "Entreprenör", "member_ids": [(4, contractor.id)]}
        )
        request = self._apartment_request(maintenance_team_id=contractor_team.id)
        self._set_district(request)
        with self.assertRaises(UserError):
            request.with_user(contractor).action_assign_district_team()
        self.assertEqual(request.maintenance_team_id, contractor_team)

    # ------------------------------------------------------------------
    # Seed data / cron / refactor
    # ------------------------------------------------------------------
    def test_district_teams_seeded_with_cost_centers(self):
        ref = self.env.ref
        self.assertEqual(ref("onecore_maintenance_extension.2").cost_center_code, "61140")
        self.assertEqual(ref("onecore_maintenance_extension.3").cost_center_code, "61130")
        self.assertEqual(ref("onecore_maintenance_extension.4").cost_center_code, "61120")
        self.assertEqual(ref("onecore_maintenance_extension.5").cost_center_code, "61110")
        self.assertEqual(ref("onecore_maintenance_extension.6").cost_center_code, "61150")
        self.assertFalse(ref("onecore_maintenance_extension.7").cost_center_code)

    def test_crons_exist_with_separate_cadences(self):
        """Two jobs: the master sync is nightly (one call for 33 areas), the
        backfill hourly (cost is the trees, not the batch size)."""
        backfill = self.env.ref(
            "onecore_maintenance_extension.ir_cron_backfill_management_area"
        )
        sync = self.env.ref("onecore_maintenance_extension.ir_cron_sync_kvv_areas")

        for cron in (backfill, sync):
            self.assertEqual(cron.model_id.model, "maintenance.request")
            self.assertTrue(cron.active)

        self.assertIn("_cron_backfill_management_area", backfill.code)
        self.assertEqual((backfill.interval_number, backfill.interval_type), (1, "hours"))
        self.assertIn("_cron_sync_kvv_areas", sync.code)
        self.assertEqual((sync.interval_number, sync.interval_type), (1, "days"))

    def test_open_time_report_uses_property_code_chain(self):
        apartment = self._apartment_request(estate_code="2201")
        self.assertIn("p=2201", apartment.open_time_report()["url"])

        building_request = create_maintenance_request(self.env, space_caption="Byggnad")
        building = create_building(
            self.env, maintenance_request_id=building_request.id, property_code="6601"
        )
        building_request.building_id = building.id
        self.assertIn("p=6601", building_request.open_time_report()["url"])
