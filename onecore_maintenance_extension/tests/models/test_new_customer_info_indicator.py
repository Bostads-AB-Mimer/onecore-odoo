"""Tests for the "Ny kundinfo" notification (MIM-1844).

Acknowledgement is shared within each audience and split between them:
one timestamp for Mimer, one for external contractors.
"""
import importlib.util
import os
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


def _load_ack_baseline_migration():
    """Load migrations/19.0.1.0.4/post-migration.py by path.

    The migration lives outside the importable package tree (the directory and
    file names are not valid Python identifiers), so it has to be loaded from
    its file location.
    """
    module_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(module_root, "migrations", "19.0.1.0.4", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_1844_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
        self.request.new_customer_info_ack_at = first.date + timedelta(seconds=1)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

        later = _post_customer_info(
            self.request, self.mimer_user, self.internal_user, body="Mer info"
        )
        later.date = self.request.new_customer_info_ack_at + timedelta(seconds=1)
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

    def test_external_ack_clears_own_side_only(self):
        # Audience split: a contractor acks their own side and must never
        # suppress the tenant's message for Mimer.
        self.request.recently_added_tenant = True
        record = self._refresh(self.external_user)
        self.assertTrue(record.has_unread_new_customer_info)

        record.action_acknowledge_new_customer_info()

        self.assertTrue(self.request.new_customer_info_external_ack_at)
        self.assertFalse(self.request.new_customer_info_ack_at)
        self.assertTrue(self.request.recently_added_tenant)
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)
        self.assertTrue(self._refresh(self.internal_user).has_unread_new_customer_info)

    def test_internal_ack_clears_own_side_only(self):
        record = self._refresh(self.internal_user)
        record.action_acknowledge_new_customer_info()

        self.assertTrue(self.request.new_customer_info_ack_at)
        self.assertFalse(self.request.new_customer_info_external_ack_at)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)
        self.assertTrue(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_new_message_after_external_ack_reappears(self):
        record = self._refresh(self.external_user)
        record.action_acknowledge_new_customer_info()
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

        later = _post_customer_info(
            self.request, self.mimer_user, self.internal_user, body="Mer info"
        )
        later.date = self.request.new_customer_info_external_ack_at + timedelta(
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
        self.assertIn("Ny kundinfo kvitterad av entreprenör", bodies)

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
        self.assertIn("Ny kundinfo kvitterad", bodies)
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


@tagged("onecore", "mim_1844")
class TestNewCustomerInfoAckBaseline(TransactionCase):
    """MIM-1844 cutover (migrations/19.0.1.0.4).

    The two ack columns are new, and the compute deliberately ignores
    mail.notification.is_read — so without a baseline every request with any
    historical Mina-sidor notification would resurface as unread. The
    post-migration seeds Mimer's ack from the old read state and gives
    contractors, who never had this badge, a clean slate.
    """

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.migration = _load_ack_baseline_migration()

    def _request(self):
        return create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )

    def _notifications(self, request, partner=None):
        """Every inbox notification on the request, looked up fresh.

        message_post() also notifies followers, so tests must set the read
        state over the whole request rather than only the rows they created.
        """
        domain = [
            ("mail_message_id.model", "=", "maintenance.request"),
            ("mail_message_id.res_id", "=", request.id),
            ("notification_type", "=", "inbox"),
        ]
        if partner:
            domain.append(("res_partner_id", "=", partner.id))
        return self.env["mail.notification"].sudo().search(domain)

    def _baseline(self):
        return self.migration._baseline_new_customer_info_acks(self.env)

    def _unread_for(self, request, user):
        record = request.with_user(user)
        record.invalidate_recordset(["has_unread_new_customer_info"])
        return record.has_unread_new_customer_info

    def test_fully_read_history_is_baselined_as_acknowledged(self):
        request = self._request()
        message = _post_customer_info(request, self.mimer_user, self.internal_user)
        self._notifications(request).write({"is_read": True})

        baselined, still_unread = self._baseline()

        self.assertEqual(baselined, 1)
        self.assertEqual(still_unread, 0)
        self.assertEqual(request.new_customer_info_ack_at, message.date)
        self.assertEqual(request.new_customer_info_external_ack_at, message.date)
        self.assertFalse(self._unread_for(request, self.internal_user))
        self.assertFalse(self._unread_for(request, self.external_user))

    def test_unread_history_stays_flagged_for_mimer_only(self):
        request = self._request()
        message = _post_customer_info(request, self.mimer_user, self.internal_user)
        self._notifications(request).write({"is_read": True})
        self._notifications(request, self.internal_user.partner_id).write(
            {"is_read": False}
        )

        baselined, still_unread = self._baseline()

        self.assertEqual(baselined, 1)
        self.assertEqual(still_unread, 1)
        self.assertFalse(request.new_customer_info_ack_at)
        self.assertEqual(request.new_customer_info_external_ack_at, message.date)
        self.assertTrue(self._unread_for(request, self.internal_user))
        self.assertFalse(self._unread_for(request, self.external_user))

    def test_contractor_unread_does_not_keep_it_flagged_for_mimer(self):
        # Before MIM-1844 the badge was per-user and contractors never had it,
        # so a contractor's unread inbox row says nothing about Mimer's state.
        request = self._request()
        message = _post_customer_info(request, self.mimer_user, self.external_user)
        self._notifications(request).write({"is_read": True})
        self._notifications(request, self.external_user.partner_id).write(
            {"is_read": False}
        )

        self._baseline()

        self.assertEqual(request.new_customer_info_ack_at, message.date)
        self.assertFalse(self._unread_for(request, self.internal_user))

    def test_request_without_customer_info_history_is_left_alone(self):
        request = self._request()

        baselined, _still_unread = self._baseline()

        self.assertEqual(baselined, 0)
        self.assertFalse(request.new_customer_info_ack_at)
        self.assertFalse(request.new_customer_info_external_ack_at)

    def test_baseline_uses_the_latest_message(self):
        request = self._request()
        first = _post_customer_info(request, self.mimer_user, self.internal_user)
        latest = _post_customer_info(
            request, self.mimer_user, self.internal_user, body="Mer info"
        )
        latest.sudo().date = first.date + timedelta(hours=1)
        self._notifications(request).write({"is_read": True})

        self._baseline()

        self.assertEqual(request.new_customer_info_ack_at, latest.date)

    def test_rerun_does_not_overwrite_a_post_upgrade_ack(self):
        request = self._request()
        message = _post_customer_info(request, self.mimer_user, self.internal_user)
        self._notifications(request).write({"is_read": True})
        self._baseline()

        acked_after_upgrade = message.date + timedelta(hours=2)
        request.write(
            {
                "new_customer_info_ack_at": acked_after_upgrade,
                "new_customer_info_external_ack_at": acked_after_upgrade,
            }
        )

        baselined, _still_unread = self._baseline()

        self.assertEqual(baselined, 0)
        self.assertEqual(request.new_customer_info_ack_at, acked_after_upgrade)
        self.assertEqual(
            request.new_customer_info_external_ack_at, acked_after_upgrade
        )
