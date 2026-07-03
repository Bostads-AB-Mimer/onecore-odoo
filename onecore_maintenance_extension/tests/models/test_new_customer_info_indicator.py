"""Tests for the "Ny kundinfo" shared notification (MIM-1844)."""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


def _get_or_create_mimer_user(env):
    """The integration account Mina sidor posts tenant communications as."""
    user = env["res.users"].sudo().search([("login", "=", "odoo@mimer.nu")], limit=1)
    if not user:
        user = env["res.users"].sudo().create(
            {
                "name": "Mimer Integration",
                "login": "odoo@mimer.nu",
                # message_post() creates a mail.message tied to the request,
                # which requires write access on maintenance.request. Mirror the
                # internal-handler groups so the record rule lets the post
                # through (base.group_user alone fails the team record rule).
                "group_ids": [
                    (
                        6,
                        0,
                        [
                            env.ref("base.group_user").id,
                            env.ref("maintenance.group_equipment_manager").id,
                        ],
                    )
                ],
            }
        )
    return user


def _post_customer_info(request, mimer_user, body="Ny info från hyresgäst"):
    """Post a comment authored by odoo@mimer.nu, as Mina sidor would."""
    return request.with_user(mimer_user).message_post(
        body=body, message_type="comment", subtype_xmlid="mail.mt_comment"
    )


@tagged("onecore")
class TestHasUnreadNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.request = create_maintenance_request(self.env)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_internal_user_sees_unread_after_customer_message(self):
        _post_customer_info(self.request, self.mimer_user)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_external_contractor_never_sees_it(self):
        _post_customer_info(self.request, self.mimer_user)
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_no_customer_message_means_no_unread(self):
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_recently_added_tenant_raises_flag(self):
        self.request.recently_added_tenant = True
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_reading_record_does_not_clear_flag(self):
        # Regression vs the old per-user inbox behaviour: merely opening/reading
        # the record must NOT clear the shared flag.
        _post_customer_info(self.request, self.mimer_user)
        record = self._refresh(self.internal_user)
        _ = record.name  # simulate opening the form
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_new_message_after_ack_reappears(self):
        first = _post_customer_info(self.request, self.mimer_user)
        self.request.new_customer_info_ack_at = first.date + timedelta(seconds=1)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

        later = _post_customer_info(self.request, self.mimer_user, body="Mer info")
        later.date = self.request.new_customer_info_ack_at + timedelta(seconds=1)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)


@tagged("onecore")
class TestAcknowledgeNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.request = create_maintenance_request(self.env)
        _post_customer_info(self.request, self.mimer_user)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_ack_sets_shared_timestamp_and_clears_flag(self):
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_new_customer_info)

        record.action_acknowledge_new_customer_info()
        self.assertTrue(self.request.new_customer_info_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_ack_clears_recently_added_tenant(self):
        self.request.recently_added_tenant = True
        record = self._refresh(self.internal_user)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(self.request.recently_added_tenant)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_ack_invalidates_flag_without_manual_refresh(self):
        record = self.request.with_user(self.internal_user)
        self.assertTrue(record.has_unread_new_customer_info)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(record.has_unread_new_customer_info)

    def test_external_contractor_cannot_ack(self):
        # Hard constraint: "Ny kundinfo" is internal-Mimer only. An external
        # contractor must never be able to clear the shared flag for
        # everyone on the Mimer side.
        self.request.recently_added_tenant = True
        record = self._refresh(self.external_user)

        record.action_acknowledge_new_customer_info()

        self.assertFalse(self.request.new_customer_info_ack_at)
        self.assertTrue(self.request.recently_added_tenant)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)
