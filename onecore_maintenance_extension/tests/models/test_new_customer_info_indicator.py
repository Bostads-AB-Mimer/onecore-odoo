"""Tests for the "Ny kundinfo" notification (MIM-1844).

Acknowledgement is shared within each audience and split between them:
one timestamp for Mimer, one for external contractors.
"""
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


def _post_customer_info(
    request, mimer_user, recipient, body="Ny info från hyresgäst", is_read=False
):
    """Post a message authored by odoo@mimer.nu that generates an inbox
    notification, as Mina sidor does."""
    message = request.with_user(mimer_user).message_post(
        body=body, message_type="comment", subtype_xmlid="mail.mt_comment"
    )
    request.env["mail.notification"].sudo().create(
        {
            "mail_message_id": message.id,
            "res_partner_id": recipient.partner_id.id,
            "notification_type": "inbox",
            "is_read": is_read,
        }
    )
    return message


@tagged("onecore")
class TestHasUnreadNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        # The external-contractor record rule (security/maintenance.xml) only
        # grants access to requests on the contractor's own team, same as
        # test_dialog_indicator.py.
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_internal_user_sees_unread_after_customer_message(self):
        _post_customer_info(self.request, self.mimer_user, self.internal_user)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_external_contractor_sees_tenant_message(self):
        # The contractor reads the tenant's Mina-sidor message in the same
        # chatter, so the badge is actionable for them too (MIM-1844 review).
        _post_customer_info(self.request, self.mimer_user, self.internal_user)
        self.assertTrue(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_external_contractor_does_not_see_recently_added_tenant(self):
        # recently_added_tenant is a Mimer-internal data-quality flag (tenant
        # back-filled from the OneCore API) — not tenant communication.
        self.request.recently_added_tenant = True
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_no_customer_message_means_no_unread(self):
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_recently_added_tenant_raises_flag(self):
        self.request.recently_added_tenant = True
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_reading_record_does_not_clear_flag(self):
        # Regression vs the old per-user inbox behaviour: merely opening/reading
        # the record must NOT clear the shared flag.
        _post_customer_info(self.request, self.mimer_user, self.internal_user)
        record = self._refresh(self.internal_user)
        _ = record.name  # simulate opening the form
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_new_message_after_ack_reappears(self):
        first = _post_customer_info(self.request, self.mimer_user, self.internal_user)
        self.request.customer_message_ack_at = first.date + timedelta(seconds=1)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

        later = _post_customer_info(
            self.request, self.mimer_user, self.internal_user, body="Mer info"
        )
        later.date = self.request.customer_message_ack_at + timedelta(seconds=1)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_mimer_message_without_inbox_notification_ignored(self):
        # Field-tracking / log notes authored by odoo@mimer.nu (e.g. automatic
        # notes) do not generate an inbox notification and must not be
        # mistaken for genuine Mina-sidor tenant communications.
        self.request.with_user(self.mimer_user).message_post(
            body="Interne notering",
            message_type="notification",
            subtype_xmlid="mail.mt_note",
        )
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)


@tagged("onecore")
class TestAcknowledgeNewCustomerInfo(TransactionCase):
    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        # The external-contractor record rule (security/maintenance.xml) only
        # grants access to requests on the contractor's own team, same as
        # test_dialog_indicator.py.
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )
        _post_customer_info(self.request, self.mimer_user, self.internal_user)

    def _refresh(self, user):
        record = self.request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record

    def test_ack_sets_shared_timestamp_and_clears_flag(self):
        record = self._refresh(self.internal_user)
        self.assertTrue(record.has_unread_new_customer_info)

        record.action_acknowledge_new_customer_info()
        self.assertTrue(self.request.customer_message_ack_at)
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

    def test_external_ack_clears_own_side_only(self):
        # Audience split: a contractor acks their own side and must never
        # suppress the tenant's message for Mimer.
        self.request.recently_added_tenant = True
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_new_customer_info)

        record.action_acknowledge_new_customer_info()

        self.assertTrue(self.request.customer_message_external_ack_at)
        self.assertFalse(self.request.customer_message_ack_at)
        self.assertTrue(self.request.recently_added_tenant)
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_internal_ack_clears_own_side_only(self):
        record = self._refresh(self.internal_user)
        record.action_acknowledge_new_customer_info()

        self.assertTrue(self.request.customer_message_ack_at)
        self.assertFalse(self.request.customer_message_external_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)
        self.assertTrue(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_new_message_after_external_ack_reappears(self):
        record = self._refresh(self.external_user)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

        later = _post_customer_info(
            self.request, self.mimer_user, self.internal_user, body="Mer info"
        )
        later.date = self.request.customer_message_external_ack_at + timedelta(
            seconds=1
        )
        self.assertTrue(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_external_ack_posts_swedish_note(self):
        record = self._refresh(self.external_user).with_context(
            creating_records=False
        )
        before = set(record.message_ids.ids)
        record.action_acknowledge_new_customer_info()
        record.invalidate_recordset(["message_ids"])
        bodies = " ".join(
            record.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        self.assertIn("Meddelande från kund kvitterat av entreprenör", bodies)

    def test_ack_posts_swedish_note_and_no_english_flag_note(self):
        self.request.recently_added_tenant = True
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_maintenance_workflow_service.py does.
        record = self._refresh(self.internal_user).with_context(
            creating_records=False
        )
        before = set(record.message_ids.ids)
        record.action_acknowledge_new_customer_info()
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it
        # must be explicitly invalidated to see the note just posted.
        record.invalidate_recordset(["message_ids"])
        bodies = " ".join(
            record.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        self.assertIn("Meddelande från kund kvitterat", bodies)
        self.assertNotIn("Recently added tenant", bodies)


@tagged("onecore")
class TestRecentlyAddedTenantFormVisibility(TransactionCase):
    """The "Ny hyresgäst, ärendet är uppdaterat" marker on the shared request
    form is a Mimer-internal data-quality badge, like the internal-only branch
    in _compute_has_unread_new_customer_info. There is only one request form
    view, and external contractors use it too, so the marker needs an explicit
    group guard (MIM-1844 review).
    """

    MARKER = "Ny hyresgäst, ärendet är uppdaterat"

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)

    def _form_arch(self, user):
        return (
            self.env["maintenance.request"]
            .with_user(user)
            .get_view(view_type="form")["arch"]
        )

    def test_internal_user_gets_the_marker(self):
        self.assertIn(self.MARKER, self._form_arch(self.internal_user))

    def test_external_contractor_does_not_get_the_marker(self):
        self.assertNotIn(self.MARKER, self._form_arch(self.external_user))
