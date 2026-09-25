# -*- coding: utf-8 -*-
"""Tests for the time report wizard ("Rapportera tid")."""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...models.maintenance_time_report_wizard import JOB_TYPES
from ...models.services import time_report_service as trs_module
from ...models.services.time_report_service import TimeReportService
from ..utils.test_utils import (
    create_building,
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
)
from .services.test_management_area_service import (
    CORE_API_PATH,
    ManagementAreaTestMixin,
    kvv_payload,
)

REQUESTS_POST = (
    "odoo.addons.onecore_maintenance_extension.models.services."
    "time_report_service.requests.post"
)
API_URL = "https://apps.mimer.nu/api/1.1/wf"
USER_EXISTS = (
    "odoo.addons.onecore_maintenance_extension.models.services."
    "time_report_service.TimeReportService.user_exists"
)


def ok_response():
    response = MagicMock(ok=True, status_code=200)
    response.json.return_value = {"status": "success"}
    return response


@tagged("onecore")
class TestMaintenanceTimeReportWizard(ManagementAreaTestMixin, TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("time_report_api_url", API_URL)
        # The app user lookup is covered by its own tests below; every other
        # test runs as a user that exists in the app.
        user_exists = patch(USER_EXISTS, return_value=True)
        self.user_exists = user_exists.start()
        self.addCleanup(user_exists.stop)
        # root is in group_external_contractor, so run as a real internal user.
        self.user = create_internal_user(
            self.env, email="tekniker@mimer.nu", tz="Europe/Stockholm"
        )
        self.request = self._apartment_request(estate_code="15103")
        self._set_district(self.request, cc_code="61130", cc_name="Distrikt Öst")
        self.request = self.request.with_user(self.user)

    def _open_wizard(self):
        action = self.request.open_time_report_wizard()
        return self.env[action["res_model"]].with_user(self.user).browse(
            action["res_id"]
        )

    def _wizard_at_job_type(self, hours=2):
        wizard = self._open_wizard()
        wizard.action_today()
        wizard.hours_spent = hours
        wizard.action_confirm_hours()
        return wizard

    @staticmethod
    def _submit(wizard, job_type):
        wizard.job_type = job_type
        return wizard.action_submit()

    # ------------------------------------------------------------------
    # Opening
    # ------------------------------------------------------------------
    def test_open_prefills_property_district_and_work_order(self):
        wizard = self._open_wizard()
        self.assertEqual(wizard.property_code, "15103")
        self.assertEqual(wizard.cost_center_code, "61130")
        self.assertEqual(wizard.work_order_id, f"od-{self.request.id}")
        self.assertEqual(wizard.step, "date")

    def test_open_uses_building_property_code(self):
        request = create_maintenance_request(self.env, space_caption="Byggnad")
        building = create_building(
            self.env, maintenance_request_id=request.id, property_code="6601"
        )
        request.building_id = building.id
        action = request.with_user(self.user).open_time_report_wizard()
        wizard = self.env[action["res_model"]].browse(action["res_id"])
        self.assertEqual(wizard.property_code, "6601")
        self.assertFalse(wizard.property_missing)

    def test_external_contractor_cannot_open_or_create(self):
        contractor = create_external_contractor_user(self.env)
        with self.assertRaises(AccessError):
            self.request.with_user(contractor).open_time_report_wizard()
        with self.assertRaises(AccessError):
            self.env["maintenance.time.report.wizard"].with_user(contractor).create(
                {"maintenance_request_id": self.request.id}
            )

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def test_today_and_yesterday_set_date_and_advance(self):
        wizard = self._open_wizard()
        today = fields.Date.context_today(wizard)

        wizard.action_today()
        self.assertEqual(wizard.date_for_work, today)
        self.assertEqual(wizard.step, "hours")

        wizard.action_back()
        self.assertEqual(wizard.step, "date")
        wizard.action_yesterday()
        self.assertEqual(wizard.date_for_work, today - timedelta(days=1))

    def test_chosen_date_rejects_future_and_missing_date(self):
        wizard = self._open_wizard()
        self.assertEqual(wizard.date_for_work, fields.Date.context_today(wizard))
        wizard.date_for_work = False
        with self.assertRaises(UserError):
            wizard.action_confirm_date()

        wizard.date_for_work = fields.Date.context_today(wizard) + timedelta(days=1)
        with self.assertRaises(UserError):
            wizard.action_confirm_date()

        wizard.date_for_work = fields.Date.to_date("2026-01-15")
        wizard.action_confirm_date()
        self.assertEqual(wizard.step, "hours")
        self.assertEqual(wizard.date_for_work, fields.Date.to_date("2026-01-15"))

    def test_hours_must_be_within_limits(self):
        wizard = self._open_wizard()
        wizard.action_today()
        for hours in (0, -1, 25):
            wizard.hours_spent = hours
            with self.assertRaises(UserError):
                wizard.action_confirm_hours()
        wizard.hours_spent = 1.5
        wizard.action_confirm_hours()
        self.assertEqual(wizard.step, "job_type")
        wizard.action_back()
        self.assertEqual(wizard.step, "hours")

    def test_weekday_label_is_swedish(self):
        wizard = self._open_wizard()
        wizard.date_for_work = fields.Date.to_date("2026-09-25")
        self.assertEqual(wizard.weekday_label, "Fredag")

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def test_payload_per_job_type(self):
        expected = {
            "repair_appliance": ("Reparation Vitvara", "622"),
            "painting": ("Måleri", "624"),
            "carpentry": ("Snickeri", "622"),
            "operations": ("Drift", "621"),
        }
        self.assertEqual(JOB_TYPES, expected)

        wizard = self._wizard_at_job_type(hours=2)
        wizard.date_for_work = fields.Date.to_date("2026-06-19")
        for job_type, (type_of_job, cost_pool) in expected.items():
            wizard.job_type = job_type
            payload = wizard._build_payload()
            self.assertEqual(payload["typeOfJob"], type_of_job)
            self.assertEqual(payload["costPool"], cost_pool)

        self.assertEqual(payload["contractorEmail"], "tekniker@mimer.nu")
        self.assertEqual(payload["KST"], "61130")
        self.assertEqual(payload["propertyCode"], "15103")
        self.assertEqual(payload["workOrderId"], f"od-{self.request.id}")
        self.assertEqual(payload["hoursSpent"], 2)
        self.assertTrue(payload["dateForWork"].startswith("2026-06-19T"))
        self.assertTrue(payload["dateForWork"].endswith("+02:00"))

        wizard.date_for_work = fields.Date.to_date("2026-01-15")
        self.assertTrue(wizard._build_payload()["dateForWork"].endswith("+01:00"))

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def test_submit_posts_to_api_and_logs_in_chatter(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "time_report_api_token", "secret"
        )
        wizard = self._wizard_at_job_type()
        with patch(REQUESTS_POST, return_value=ok_response()) as mock_post:
            action = self._submit(wizard, "painting")

        mock_post.assert_called_once()
        self.assertEqual(
            mock_post.call_args.args[0], f"{API_URL}/create_time_report"
        )
        kwargs = mock_post.call_args.kwargs
        self.assertEqual(kwargs["json"]["typeOfJob"], "Måleri")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(action["tag"], "display_notification")
        self.request.invalidate_recordset(["message_ids"])
        self.assertIn(
            "Tid rapporterad: 2 h Måleri",
            self.request.message_ids[0].body,
        )

    def test_no_authorization_header_without_token(self):
        self.env["ir.config_parameter"].sudo().set_param("time_report_api_token", "")
        wizard = self._wizard_at_job_type()
        with patch(REQUESTS_POST, return_value=ok_response()) as mock_post:
            self._submit(wizard, "operations")
        self.assertNotIn("Authorization", mock_post.call_args.kwargs["headers"])

    def test_api_error_raises_and_skips_chatter(self):
        wizard = self._wizard_at_job_type()
        message_count = len(self.request.message_ids)

        failed = MagicMock(ok=False, status_code=500, text="boom")
        with patch(REQUESTS_POST, return_value=failed):
            with self.assertRaises(UserError):
                self._submit(wizard, "carpentry")
        with patch(REQUESTS_POST, side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(UserError):
                self._submit(wizard, "carpentry")

        self.request.invalidate_recordset(["message_ids"])
        self.assertEqual(len(self.request.message_ids), message_count)

    def test_submit_requires_job_type(self):
        wizard = self._wizard_at_job_type()
        with patch(REQUESTS_POST) as mock_post:
            with self.assertRaises(UserError):
                wizard.action_submit()
        mock_post.assert_not_called()

    def test_missing_district_blocks_submit(self):
        self._set_district(self.request, cc_code=False, cc_name=False)
        wizard = self._wizard_at_job_type()
        with patch(REQUESTS_POST) as mock_post:
            with self.assertRaises(UserError):
                self._submit(wizard, "painting")
        mock_post.assert_not_called()

    def test_missing_api_url_warns_logs_and_blocks_submit(self):
        self.env["ir.config_parameter"].sudo().set_param("time_report_api_url", False)
        with self.assertLogs(
            "odoo.addons.onecore_maintenance_extension.models.services."
            "time_report_service",
            level="ERROR",
        ) as logs:
            wizard = self._wizard_at_job_type()
        self.assertIn("time_report_api_url", logs.output[0])
        self.assertFalse(wizard.api_configured)

        with patch(REQUESTS_POST) as mock_post:
            with self.assertRaises(UserError):
                self._submit(wizard, "painting")
        mock_post.assert_not_called()

    def test_configured_api_url_shows_no_warning(self):
        self.assertTrue(self._open_wizard().api_configured)

    # ------------------------------------------------------------------
    # Request without property: search one up
    # ------------------------------------------------------------------
    def _wizard_without_property(self):
        request = create_maintenance_request(self.env, space_caption="Fastighet")
        action = request.with_user(self.user).open_time_report_wizard()
        return self.env[action["res_model"]].with_user(self.user).browse(
            action["res_id"]
        )

    def _search_property(self, wizard, core_api, properties, district=None):
        core_api.return_value.fetch_properties.return_value = properties
        core_api.return_value.fetch_kvv_area_for_property.return_value = district
        wizard.property_search = "MINKEN"
        result = wizard._onchange_property_search()
        wizard._onchange_property_option_id()
        return result

    def test_request_without_property_requires_search(self):
        wizard = self._wizard_without_property()
        self.assertTrue(wizard.property_missing)
        self.assertFalse(wizard.property_code)
        with self.assertRaises(UserError):
            wizard.action_today()

    def test_property_search_sets_property_and_district(self):
        self._configure_onecore()
        wizard = self._wizard_without_property()
        with patch(CORE_API_PATH) as core_api:
            self._search_property(
                wizard,
                core_api,
                [{"property": {"code": "15103", "designation": "MINKEN 1"}}],
                district=kvv_payload(cc_code="61130"),
            )
            core_api.return_value.fetch_properties.assert_called_once_with(
                "MINKEN", "Fastighet"
            )
        self.assertEqual(wizard.property_option_id.designation, "MINKEN 1")
        self.assertEqual(wizard.property_code, "15103")
        self.assertEqual(wizard.cost_center_code, "61130")

        wizard.action_today()
        wizard.hours_spent = 1
        wizard.action_confirm_hours()
        with patch(REQUESTS_POST, return_value=ok_response()) as mock_post:
            self._submit(wizard, "operations")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["propertyCode"], "15103")
        self.assertEqual(payload["KST"], "61130")

    def test_property_search_without_hits_warns(self):
        wizard = self._wizard_without_property()
        with patch(CORE_API_PATH) as core_api:
            result = self._search_property(wizard, core_api, [])
        self.assertIn("warning", result)
        self.assertFalse(wizard.property_code)

    def test_searched_property_without_district_blocks_submit(self):
        self._configure_onecore()
        wizard = self._wizard_without_property()
        with patch(CORE_API_PATH) as core_api:
            self._search_property(
                wizard,
                core_api,
                [{"property": {"code": "99999", "designation": "UTAN DISTRIKT"}}],
                district=None,
            )
        self.assertEqual(wizard.property_code, "99999")
        self.assertFalse(wizard.cost_center_code)
        wizard.action_today()
        wizard.hours_spent = 1
        wizard.action_confirm_hours()
        with patch(REQUESTS_POST) as mock_post:
            with self.assertRaises(UserError):
                self._submit(wizard, "operations")
        mock_post.assert_not_called()

    # ------------------------------------------------------------------
    # User must exist in the time reporting app
    # ------------------------------------------------------------------
    def test_unknown_app_user_blocks_modal_and_submit(self):
        self.user_exists.return_value = False
        wizard = self._open_wizard()
        self.assertIn(
            "Användaren saknas i tidsrapporteringsappen apps.mimer.nu (Bubble)",
            wizard.user_check_message,
        )
        self.assertTrue(wizard.app_user_missing)
        with self.assertRaises(UserError):
            wizard.action_today()

        # Even when the steps are bypassed, submit re-checks.
        wizard.write(
            {"step": "job_type", "hours_spent": 1, "user_check_message": False}
        )
        with patch(REQUESTS_POST) as mock_post:
            with self.assertRaises(UserError):
                self._submit(wizard, "painting")
        mock_post.assert_not_called()

    def test_failed_user_lookup_blocks_modal(self):
        self.user_exists.side_effect = UserError("Kunde inte nå tidsrapporteringen.")
        wizard = self._open_wizard()
        self.assertEqual(wizard.user_check_message, "Kunde inte nå tidsrapporteringen.")
        self.assertFalse(wizard.app_user_missing)

    def test_recheck_unblocks_after_login_in_app(self):
        self.user_exists.return_value = False
        wizard = self._open_wizard()
        self.assertTrue(wizard.user_check_message)

        self.user_exists.return_value = True
        wizard.action_recheck_user()
        self.assertFalse(wizard.user_check_message)
        self.assertFalse(wizard.app_user_missing)
        wizard.action_today()
        self.assertEqual(wizard.step, "hours")

    def test_open_time_report_app_uses_parameter(self):
        wizard = self._open_wizard()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("time_report_base_url", False)
        action = wizard.action_open_time_report_app()
        self.assertEqual(action["url"], "https://apps.mimer.nu/tidsrapportering")
        self.assertEqual(action["target"], "new")

        params.set_param("time_report_base_url", "https://apps.mimer.nu/version-test/tidsrapportering/")
        self.assertIn("version-test", wizard.action_open_time_report_app()["url"])

    def test_known_app_user_is_not_blocked(self):
        wizard = self._open_wizard()
        self.assertFalse(wizard.user_check_message)
        self.user_exists.assert_called_with("tekniker@mimer.nu")


@tagged("onecore")
class TestTimeReportServiceUserLookup(TransactionCase):
    def setUp(self):
        super().setUp()
        trs_module._user_cache.clear()
        self.env["ir.config_parameter"].sudo().set_param("time_report_api_url", API_URL)
        self.service = TimeReportService(self.env)

    def _response(self, body):
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = body
        return response

    def test_user_found(self):
        found = self._response(
            {"status": "success", "response": {"email": "david.lindblom@mimer.nu"}}
        )
        with patch(REQUESTS_POST, return_value=found) as mock_post:
            self.assertTrue(self.service.user_exists("david.lindblom@mimer.nu"))
        self.assertEqual(mock_post.call_args.args[0], f"{API_URL}/get_user_by_email")
        self.assertEqual(
            mock_post.call_args.kwargs["json"], {"email": "david.lindblom@mimer.nu"}
        )

    def test_user_found_flat_response(self):
        found = self._response({"email": "david.lindblom@mimer.nu"})
        with patch(REQUESTS_POST, return_value=found):
            self.assertTrue(self.service.user_exists("david.lindblom@mimer.nu"))

    def test_user_found_other_shape(self):
        found = self._response(
            {"status": "success", "response": {"user": {"Email": "a@mimer.nu"}}}
        )
        with patch(REQUESTS_POST, return_value=found):
            self.assertTrue(self.service.user_exists("a@mimer.nu"))

    def test_user_missing(self):
        missing = self._response({"status": "success", "response": {}})
        with patch(REQUESTS_POST, return_value=missing):
            self.assertFalse(self.service.user_exists("okand@mimer.nu"))

    def test_found_user_is_cached_missing_is_not(self):
        found = self._response({"response": {"email": "a@mimer.nu"}})
        missing = self._response({"response": {}})
        with patch(REQUESTS_POST, return_value=found) as mock_post:
            self.service.user_exists("a@mimer.nu")
            self.service.user_exists("A@mimer.nu")
        self.assertEqual(mock_post.call_count, 1)
        with patch(REQUESTS_POST, return_value=missing) as mock_post:
            self.service.user_exists("b@mimer.nu")
            self.service.user_exists("b@mimer.nu")
        self.assertEqual(mock_post.call_count, 2)

    def test_lookup_error_raises(self):
        with patch(REQUESTS_POST, side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(UserError):
                self.service.user_exists("a@mimer.nu")

    def test_legacy_full_create_url_still_works(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "time_report_api_url", f"{API_URL}/create_time_report"
        )
        found = self._response({"response": {"email": "a@mimer.nu"}})
        with patch(REQUESTS_POST, return_value=found) as mock_post:
            self.service.user_exists("a@mimer.nu")
        self.assertEqual(mock_post.call_args.args[0], f"{API_URL}/get_user_by_email")
