"""Tests for OneCoreFlagSyncService (MIM-1959) — the batch refresh of the two
OneCore safety flags behind the kanban badges.

OneCore is always mocked (patch CoreApi); ``onecore_base_url`` is only set in
tests that expect a call, because the service refuses to construct the client
without it.
"""

import time
from unittest.mock import patch

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...utils.test_utils import (
    create_facility,
    create_maintenance_request,
    create_parking_space,
    create_rental_property,
    create_tenant,
)
from ....models.services import onecore_flag_sync_service as sync_module
from ....models.services.onecore_flag_sync_service import OneCoreFlagSyncService

CORE_API_PATH = "odoo.addons.onecore_api.core_api.CoreApi"

BLOCKED_RENTAL_ID = "705-022-04-0201"
FREE_RENTAL_ID = "705-022-04-0202"


class FlagSyncTestMixin:
    def setUp(self):
        super().setUp()
        sync_module._pest_set_cache.clear()
        self.service = OneCoreFlagSyncService(self.env)

    def _configure_onecore(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "onecore_base_url", "https://core.test"
        )

    def _apartment_request(self, rental_id=BLOCKED_RENTAL_ID, **kwargs):
        rental_property = create_rental_property(self.env, rental_property_id=rental_id)
        request = create_maintenance_request(
            self.env,
            space_caption="Lägenhet",
            rental_property_id=rental_property.id,
            **kwargs,
        )
        return self.env["maintenance.request"].browse(request.id)

    def _mock_api(self, MockApi, blocked=None, captions=None):
        MockApi.return_value.fetch_block_reason_captions.return_value = (
            captions if captions is not None else ["SKADEDJUR", "RENOVERING"]
        )
        MockApi.return_value.fetch_pest_blocked_rental_ids.return_value = (
            blocked if blocked is not None else []
        )
        return MockApi.return_value


@tagged("onecore")
class TestRentalIdResolution(FlagSyncTestMixin, TransactionCase):
    def test_rental_id_from_rental_property(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self.assertEqual(self.service.get_rental_id(request), BLOCKED_RENTAL_ID)

    def test_rental_id_from_parking_space(self):
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        parking = create_parking_space(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="303-001-01-0001",
        )
        request.parking_space_id = parking.id
        self.assertEqual(self.service.get_rental_id(request), "303-001-01-0001")

    def test_rental_id_from_facility(self):
        request = create_maintenance_request(self.env, space_caption="Lokal")
        facility = create_facility(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="404-001-01-0001",
        )
        request.facility_id = facility.id
        self.assertEqual(self.service.get_rental_id(request), "404-001-01-0001")

    def test_no_rental_object_resolves_to_false(self):
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")
        self.assertFalse(self.service.get_rental_id(request))


@tagged("onecore")
class TestSyncPestControl(FlagSyncTestMixin, TransactionCase):
    def test_blocked_rental_id_sets_the_flag(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_lifted_block_clears_the_flag(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_unrelated_rental_id_is_untouched(self):
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_parking_space_request_gets_the_flag(self):
        """Regression: the old compute only ever called fetch_residence, so
        parking and facility cases silently resolved to False."""
        request = create_maintenance_request(self.env, space_caption="Bilplats")
        parking = create_parking_space(
            self.env,
            maintenance_request_id=request.id,
            rental_property_id="303-001-01-0001",
        )
        request.parking_space_id = parking.id
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=["303-001-01-0001"])
            self.service.sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_request_without_a_rental_object_is_cleared(self):
        """A property- or building-level case has nothing to block. If it holds
        a stale True it must be cleared, not merely skipped."""
        request = create_maintenance_request(self.env, space_caption="Tvättstuga")
        request.sudo().write({"requires_pest_control": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_fetch_failure_writes_nothing(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_block_reason_captions.return_value = [
                "SKADEDJUR"
            ]
            MockApi.return_value.fetch_pest_blocked_rental_ids.side_effect = Exception(
                "boom"
            )
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertTrue(request.requires_pest_control)

    def test_missing_caption_aborts_without_clearing(self):
        """A rename in Xpand returns an empty set that looks exactly like
        "nothing is blocked". Refuse the run rather than clear every badge."""
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"requires_pest_control": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[], captions=["RENOVERING"])
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertTrue(request.requires_pest_control)
        api.fetch_pest_blocked_rental_ids.assert_not_called()

    def test_closed_requests_are_excluded(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"closed_date": fields.Datetime.now()})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_archived_requests_are_excluded(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        request.sudo().write({"archive": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertFalse(request.requires_pest_control)

    def test_unchanged_run_writes_nothing(self):
        """Steady state must cost zero UPDATEs — that is what makes a
        15-minute cadence affordable."""
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.assertEqual(self.service.sync_pest_control(), 1)
            self.assertEqual(self.service.sync_pest_control(), 0)

        self.assertTrue(request.requires_pest_control)

    def test_unconfigured_onecore_is_a_no_op(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        with patch(CORE_API_PATH) as MockApi:
            changed = self.service.sync_pest_control()

        self.assertEqual(changed, 0)
        self.assertFalse(request.requires_pest_control)
        MockApi.assert_not_called()

    def test_flag_change_posts_no_chatter(self):
        """Spec decision 3: the badge changes silently."""
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        before = len(request.message_ids)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.service.sync_pest_control()

        self.assertEqual(len(request.message_ids), before)


@tagged("onecore")
class TestFetchPestBlockedRentalIds(FlagSyncTestMixin, TransactionCase):
    """Fix 2: the all-or-nothing contract must be explicit, not a falsy
    coercion. ``CoreApi._get_json`` returns ``None`` for a 200 whose body
    lacks "content" - that must raise, never be read as "nothing is
    blocked". A genuinely empty list must still mean a genuinely empty set.
    """

    def test_none_payload_raises(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_block_reason_captions.return_value = [
                "SKADEDJUR"
            ]
            MockApi.return_value.fetch_pest_blocked_rental_ids.return_value = None
            with self.assertRaises(ValueError):
                self.service.fetch_pest_blocked_rental_ids()

    def test_empty_list_is_a_valid_empty_set(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[])
            result = self.service.fetch_pest_blocked_rental_ids()

        self.assertEqual(result, set())


def _contact(code, special_attention):
    """Shape of one item in GET /v1/contacts/batch ``content``."""
    return {
        "contactCode": code,
        "communication": {
            "phoneNumbers": [],
            "emailAddresses": [],
            "specialAttention": special_attention,
        },
    }


@tagged("onecore")
class TestSyncSpecialAttention(FlagSyncTestMixin, TransactionCase):
    def _request_with_tenant(self, contact_code="P123456", **tenant_vals):
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)
        tenant = create_tenant(
            self.env,
            maintenance_request_id=request.id,
            contact_code=contact_code,
            **tenant_vals,
        )
        request.sudo().write({"tenant_id": tenant.id})
        return request, tenant

    def test_flag_set_in_xpand_after_creation_reaches_the_tenant(self):
        request, tenant = self._request_with_tenant("P123456")
        self.assertFalse(tenant.special_attention)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.service.sync_special_attention()

        self.assertTrue(tenant.special_attention)
        self.assertTrue(request.special_attention)

    def test_cleared_flag_is_cleared_locally(self):
        _request, tenant = self._request_with_tenant("P123456")
        tenant.sudo().write({"special_attention": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", False)
            ]
            self.service.sync_special_attention()

        self.assertFalse(tenant.special_attention)

    def test_code_missing_from_the_answer_is_left_alone(self):
        """Absent means unknown, not False."""
        _request, tenant = self._request_with_tenant("P123456")
        tenant.sudo().write({"special_attention": True})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = []
            self.service.sync_special_attention()

        self.assertTrue(tenant.special_attention)

    def test_codes_are_chunked(self):
        """Patch the size rather than create 200 records — the boundary logic
        is what matters, not the constant's value."""
        self._request_with_tenant("P000001")
        self._request_with_tenant("P000002")
        self._request_with_tenant("P000003")
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi, patch.object(
            sync_module, "CONTACT_BATCH_SIZE", 2
        ):
            MockApi.return_value.fetch_contacts_batch.return_value = []
            self.service.sync_special_attention()

        calls = MockApi.return_value.fetch_contacts_batch.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][0], ["P000001", "P000002"])
        self.assertEqual(calls[1][0][0], ["P000003"])

    def test_a_failing_chunk_does_not_lose_the_others(self):
        _r1, tenant_one = self._request_with_tenant("P000001")
        _r2, tenant_two = self._request_with_tenant("P000002")
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi, patch.object(
            sync_module, "CONTACT_BATCH_SIZE", 1
        ):
            MockApi.return_value.fetch_contacts_batch.side_effect = [
                [_contact("P000001", True)],
                Exception("boom"),
            ]
            self.service.sync_special_attention()

        self.assertTrue(tenant_one.special_attention)
        self.assertFalse(tenant_two.special_attention)

    def test_closed_requests_are_excluded(self):
        request, tenant = self._request_with_tenant("P123456")
        request.sudo().write({"closed_date": fields.Datetime.now()})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.service.sync_special_attention()

        self.assertFalse(tenant.special_attention)

    def test_unchanged_run_writes_nothing(self):
        self._request_with_tenant("P123456")
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                _contact("P123456", True)
            ]
            self.assertEqual(self.service.sync_special_attention(), 1)
            self.assertEqual(self.service.sync_special_attention(), 0)

    def test_unconfigured_onecore_is_a_no_op(self):
        self._request_with_tenant("P123456")

        with patch(CORE_API_PATH) as MockApi:
            self.assertEqual(self.service.sync_special_attention(), 0)

        MockApi.assert_not_called()


@tagged("onecore")
class TestPopulateOnCreate(FlagSyncTestMixin, TransactionCase):
    def test_new_case_on_a_blocked_object_is_flagged_immediately(self):
        """Waiting up to a cron interval is exactly the window where the badge
        would have protected whoever is sent to the flat."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            self.service.populate_pest_control(request)

        self.assertTrue(request.requires_pest_control)

    def test_new_case_on_a_free_object_is_not_flagged(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            request = self._apartment_request(rental_id=FREE_RENTAL_ID)
            self.service.populate_pest_control(request)

        self.assertFalse(request.requires_pest_control)

    def test_onecore_failure_never_blocks_creation(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_block_reason_captions.side_effect = Exception(
                "boom"
            )
            request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            self.assertFalse(self.service.populate_pest_control(request))

        self.assertFalse(request.requires_pest_control)

    def test_a_burst_of_creations_shares_one_call(self):
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            for _ in range(3):
                request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
                self.service.populate_pest_control(request)

        self.assertEqual(api.fetch_pest_blocked_rental_ids.call_count, 1)

    def test_the_cron_never_reads_the_create_cache(self):
        """A stale set is fine for one new case; it is not fine for a run that
        clears badges across the estate."""
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self._configure_onecore()
        sync_module._pest_set_cache[self.env.cr.dbname] = (
            time.monotonic() + 300,
            frozenset({BLOCKED_RENTAL_ID}),
        )

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[])
            self.service.sync_pest_control()

        api.fetch_pest_blocked_rental_ids.assert_called_once()
        self.assertFalse(request.requires_pest_control)

    def test_create_path_skips_the_caption_guard(self):
        """Fix 1a: a single create can only ever SET the flag, never clear
        one, so the caption guard buys it nothing and would cost a whole
        extra 15-second call. The cron must keep the guard."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            self.service.populate_pest_control(request)
            api.fetch_block_reason_captions.assert_not_called()

            self.service.sync_pest_control()
            api.fetch_block_reason_captions.assert_called_once()

    def test_a_failed_fetch_is_negative_cached(self):
        """Fix 1b: a burst of creations during an outage should pay the
        timeout once, not once per case - and stop believing "down" much
        sooner than it would have believed a real answer."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            api = self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            api.fetch_pest_blocked_rental_ids.side_effect = Exception("boom")

            request_one = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
            request_two = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)

        self.assertEqual(api.fetch_pest_blocked_rental_ids.call_count, 1)
        self.assertFalse(request_one.requires_pest_control)
        self.assertFalse(request_two.requires_pest_control)

    def test_create_populates_without_an_explicit_call(self):
        """The hook in create() is what makes this work in production."""
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            rental_property = create_rental_property(
                self.env, rental_property_id=BLOCKED_RENTAL_ID
            )
            request = create_maintenance_request(
                self.env,
                space_caption="Lägenhet",
                rental_property_id=rental_property.id,
            )

        self.assertTrue(request.requires_pest_control)


@tagged("onecore")
class TestFlagSyncCrons(FlagSyncTestMixin, TransactionCase):
    def test_pest_cron_delegates_to_the_service(self):
        request = self._apartment_request(rental_id=BLOCKED_RENTAL_ID)
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            self._mock_api(MockApi, blocked=[BLOCKED_RENTAL_ID])
            self.env["maintenance.request"]._cron_sync_pest_control()

        self.assertTrue(request.requires_pest_control)

    def test_special_attention_cron_delegates_to_the_service(self):
        request = self._apartment_request(rental_id=FREE_RENTAL_ID)
        tenant = create_tenant(
            self.env,
            maintenance_request_id=request.id,
            contact_code="P123456",
        )
        request.sudo().write({"tenant_id": tenant.id})
        self._configure_onecore()

        with patch(CORE_API_PATH) as MockApi:
            MockApi.return_value.fetch_contacts_batch.return_value = [
                {
                    "contactCode": "P123456",
                    "communication": {"specialAttention": True},
                }
            ]
            self.env["maintenance.request"]._cron_sync_special_attention()

        self.assertTrue(tenant.special_attention)

    def test_cron_records_exist_and_are_active(self):
        pest = self.env.ref("onecore_maintenance_extension.ir_cron_sync_pest_control")
        kundinfo = self.env.ref(
            "onecore_maintenance_extension.ir_cron_sync_special_attention"
        )

        self.assertTrue(pest.active)
        self.assertEqual(pest.interval_number, 15)
        self.assertEqual(pest.interval_type, "minutes")

        self.assertTrue(kundinfo.active)
        self.assertEqual(kundinfo.interval_number, 1)
        self.assertEqual(kundinfo.interval_type, "hours")
