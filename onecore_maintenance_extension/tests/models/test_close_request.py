"""Tests for the tenant's close request (MIM-2036).

A tenant can no longer close an Odoo case from Mina sidor. They ask, via
request_close_from_tenant, and an Odoo user decides: "Avsluta ärendet"
(action_accept_close_request) or "Avslå" with a reason (the decline wizard).
Moving the case to Avslutad any other way also resolves the request.
"""

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import SQL

from ..utils.test_utils import (
    create_external_contractor_user,
    create_internal_user,
    create_maintenance_request,
)
from .test_customer_message_indicator import _get_or_create_mimer_user
from ...models.constants import (
    CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
    CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
)
from ...models.services import FieldChangeTracker


def _sql_code(call):
    """The query text of one recorded cr.execute call."""
    query = call.args[0] if call.args else call.kwargs.get("query")
    return query.code if isinstance(query, SQL) else str(query)


@tagged("onecore")
class TestCloseRequestMessageTypes(TransactionCase):
    def test_types_are_registered_on_mail_message(self):
        # Assert on the constants, not literals, so renaming one side without
        # the other (constants.py vs onecore_mail_extension) fails here.
        selection = dict(self.env["mail.message"]._fields["message_type"].selection)
        self.assertIn(CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE, selection)
        self.assertIn(CLOSE_REQUEST_DECLINED_MESSAGE_TYPE, selection)

    def test_types_are_not_outbound_tenant_dispatch_types(self):
        # Every tenant_* type sends a real SMS/e-post in mail.message.create.
        for message_type in (
            CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE,
            CLOSE_REQUEST_DECLINED_MESSAGE_TYPE,
        ):
            with self.subTest(message_type=message_type):
                self.assertFalse(message_type.startswith("tenant_"))


class CloseRequestCase(TransactionCase):
    """Shared fixture: the integration account the work-order service calls
    as, a Mimer handler, and a contractor on the request's team.

    Staff actions always run as a dedicated user: security/maintenance.xml
    puts base.user_root — the raw test env — in group_external_contractor, so
    it would be refused a move to Avslutad like any contractor. The contractor
    record rule only grants access to requests on the contractor's own team.
    """

    def setUp(self):
        super().setUp()
        self.internal_user = create_internal_user(self.env)
        self.external_user = create_external_contractor_user(self.env)
        self.mimer_user = _get_or_create_mimer_user(self.env)
        self.team = self.env["maintenance.team"].create({"name": "Test Team"})
        self.team.write({"member_ids": [(4, self.external_user.id)]})
        self.request = create_maintenance_request(
            self.env, maintenance_team_id=self.team.id
        )
        self.stage_avslutad = self._stage("Avslutad")
        self.stage_vantar = self._stage("Väntar på handläggning")

    def _stage(self, name):
        return self.env["maintenance.stage"].search([("name", "=", name)], limit=1)

    def _as(self, user):
        return self.request.with_user(user)

    def _fresh(self):
        # Writes made through another user's env (sudo, with_user) and
        # savepoint rollbacks must not be answered from a stale cache.
        self.request.invalidate_recordset()
        return self.request

    def _messages(self, message_type):
        return self.env["mail.message"].search(
            [
                ("model", "=", "maintenance.request"),
                ("res_id", "=", self.request.id),
                ("message_type", "=", message_type),
            ]
        )


@tagged("onecore")
class TestCloseRequestPending(CloseRequestCase):
    def _stamp(self, requested=False, resolved=False):
        self.request.sudo().write(
            {"close_requested_at": requested, "close_request_resolved_at": resolved}
        )

    def test_not_pending_without_a_request(self):
        self.assertFalse(self.request.close_request_pending)

    def test_pending_once_requested(self):
        self._stamp(requested=fields.Datetime.now())
        self.assertTrue(self._fresh().close_request_pending)

    def test_resolution_after_the_request_clears_it(self):
        now = fields.Datetime.now()
        self._stamp(requested=now - timedelta(minutes=5), resolved=now)
        self.assertFalse(self._fresh().close_request_pending)

    def test_resolution_in_the_same_second_clears_it(self):
        # Datetime has second resolution; a decline within the second of the
        # request must read as resolved, not as still pending.
        now = fields.Datetime.now()
        self._stamp(requested=now, resolved=now)
        self.assertFalse(self._fresh().close_request_pending)

    def test_request_after_a_resolution_is_pending_again(self):
        now = fields.Datetime.now()
        self._stamp(requested=now, resolved=now - timedelta(minutes=5))
        self.assertTrue(self._fresh().close_request_pending)

    def test_pending_close_request_sorts_before_an_unread_customer_message(self):
        # Without the new first key, customer_message_unread desc would put
        # `other` first — so this pins both the promotion and its precedence.
        other = create_maintenance_request(self.env, maintenance_team_id=self.team.id)
        other.sudo().write({"last_customer_message_at": fields.Datetime.now()})
        self._stamp(requested=fields.Datetime.now())
        found = self.env["maintenance.request"].search(
            [("id", "in", [self.request.id, other.id])]
        )
        self.assertEqual(found.ids, [self.request.id, other.id])

    def test_stamps_post_no_change_note(self):
        # The request and the decline are chatter messages of their own, and an
        # accept is the stage change — a field-change note on top is noise.
        before = len(self.request.message_ids)
        self._as(self.internal_user).write(
            {"close_requested_at": fields.Datetime.now()}
        )
        self.assertEqual(len(self._fresh().message_ids), before)


@tagged("onecore")
class TestRequestCloseFromTenant(CloseRequestCase):
    def _request_close(self, reason=None):
        # Called exactly as onecore's work-order service does: XML-RPC as the
        # integration account.
        return self._as(self.mimer_user).request_close_from_tenant(reason=reason)

    def _requests(self):
        return self._messages(CLOSE_REQUEST_FROM_TENANT_MESSAGE_TYPE)

    def test_request_posts_the_message_and_sets_pending(self):
        self.assertIs(self._request_close(), True)
        message = self._requests()
        self.assertEqual(len(message), 1)
        self.assertIn("Begäran om att avsluta ärendet", message.body)
        self.assertNotIn("Orsak", message.body)
        self.assertEqual(message.author_id, self.mimer_user.partner_id)
        # Tenant-authored: work-order takes the sender from author_id, so no
        # tenant-facing sender may be stored (MIM-2040).
        self.assertFalse(message.onecore_tenant_author_name)
        request = self._fresh()
        self.assertTrue(request.close_requested_at)
        self.assertTrue(request.close_request_pending)

    def test_reason_follows_orsak(self):
        self._request_close(reason="  Allt fungerar igen  ")
        self.assertIn("Orsak: Allt fungerar igen", self._requests().body)

    def test_reason_containing_a_script_tag_is_escaped(self):
        self._request_close(reason='<script>alert("x")</script>')
        body = self._requests().body
        # Escaped, not sanitised away: the HTML sanitiser would drop a live
        # <script> element entirely, so the escaped text surviving is what
        # proves the reason never reached the body as markup.
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script", body)

    def test_newlines_become_line_breaks(self):
        self._request_close(reason="Rad ett\nRad två")
        self.assertIn("Rad ett<br>Rad två", self._requests().body)

    def test_whitespace_only_reason_is_treated_as_none(self):
        self._request_close(reason="   \n\t  ")
        self.assertNotIn("Orsak", self._requests().body)
        self.assertTrue(self._fresh().close_request_pending)

    def test_second_request_is_refused_as_already_pending(self):
        self._request_close()
        with self.assertRaisesRegex(
            UserError, r"^close_request_conflict:already_pending$"
        ):
            self._request_close(reason="Igen")
        self.assertEqual(len(self._requests()), 1)

    def test_refused_when_the_case_is_closed(self):
        self._as(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        with self.assertRaisesRegex(UserError, r"^close_request_conflict:closed$"):
            self._request_close()
        self.assertFalse(self._requests())
        self.assertFalse(self._fresh().close_request_pending)

    def test_refused_when_hidden_from_my_pages(self):
        self.request.write({"hidden_from_my_pages": True})
        with self.assertRaisesRegex(UserError, r"^close_request_conflict:hidden$"):
            self._request_close()
        self.assertFalse(self._requests())

    def test_row_is_locked_before_the_checks(self):
        # Two concurrent calls cannot be staged in a TransactionCase — every
        # env shares one cursor — so this pins the mechanism instead: the lock
        # is taken even on a call that is then refused, i.e. before the check.
        self._request_close()
        cr = self.env.cr
        with patch.object(cr, "execute", wraps=cr.execute) as spy:
            with self.assertRaises(UserError):
                self._request_close()
        locks = [
            c
            for c in spy.call_args_list
            if "FOR UPDATE" in _sql_code(c) and "maintenance_request" in _sql_code(c)
        ]
        self.assertTrue(locks, "request_close_from_tenant must row-lock first")
        self.assertNotIn("SKIP LOCKED", _sql_code(locks[0]))

    def test_request_right_after_a_resolution_is_pending(self):
        # Second resolution: a resolution stamped "now" would equal a request
        # stamped "now", which the compute reads as resolved.
        self.request.sudo().write(
            {
                "close_requested_at": fields.Datetime.now() - timedelta(minutes=1),
                "close_request_resolved_at": fields.Datetime.now(),
            }
        )
        self._request_close()
        request = self._fresh()
        self.assertGreater(
            request.close_requested_at, request.close_request_resolved_at
        )
        self.assertTrue(request.close_request_pending)

    def test_request_never_dispatches_a_real_sms_or_email(self):
        mail_message_cls = type(self.env["mail.message"])
        with patch.object(mail_message_cls, "_send_sms") as mock_send_sms:
            with patch.object(mail_message_cls, "_send_email") as mock_send_email:
                self._request_close(reason="Klart")
        mock_send_sms.assert_not_called()
        mock_send_email.assert_not_called()


@tagged("onecore")
class TestCloseRequestResolution(CloseRequestCase):
    def setUp(self):
        super().setUp()
        self._as(self.mimer_user).request_close_from_tenant()

    def test_accept_closes_the_case_and_resolves_the_request(self):
        self.assertIs(self._as(self.internal_user).action_accept_close_request(), True)
        request = self._fresh()
        self.assertEqual(request.stage_id, self.stage_avslutad)
        self.assertFalse(request.close_request_pending)
        self.assertEqual(request.close_request_resolved_at, request.closed_date)

    def test_contractor_cannot_accept_and_the_request_stays_pending(self):
        with self.assertRaisesRegex(
            UserError, "Du har inte behörighet att flytta detta ärende till Avslutad"
        ):
            self._as(self.external_user).action_accept_close_request()
        request = self._fresh()
        self.assertNotEqual(request.stage_id, self.stage_avslutad)
        self.assertTrue(request.close_request_pending)

    def test_stage_write_failing_after_the_update_leaves_the_request_pending(self):
        # Fails after super().write() — stage_id and close_request_resolved_at
        # are set in the same vals dict, so they are flushed to the database
        # together — so this proves the two roll back together, not merely
        # that nothing had been written yet. The rollback itself comes from
        # BaseCase.assertRaises, which wraps its block in a savepoint and
        # rolls it back on the expected exception (odoo/tests/common.py);
        # assertRaisesRegex does not, so plain assertRaises + assertIn on the
        # message is used here instead.
        #
        # create_maintenance_request() leaves `creating_records=True` on the
        # returned recordset's context (see maintenance.py create()), which
        # makes write() skip FieldChangeTracker entirely, so the patched
        # post_change_notifications below would never actually run. Same
        # override as test_master_key_change_indicator.py and
        # test_maintenance_workflow_service.py use for the same reason.
        with patch.object(
            FieldChangeTracker,
            "post_change_notifications",
            side_effect=UserError("Testfel"),
        ):
            with self.assertRaises(UserError) as cm:
                self._as(self.internal_user).with_context(
                    creating_records=False
                ).action_accept_close_request()
            self.assertIn("Testfel", str(cm.exception))
        request = self._fresh()
        self.assertNotEqual(request.stage_id, self.stage_avslutad)
        self.assertFalse(request.close_request_resolved_at)
        self.assertTrue(request.close_request_pending)

    def test_accept_when_already_handled_is_refused(self):
        self._as(self.internal_user).action_accept_close_request()
        with self.assertRaisesRegex(UserError, "Begäran om avslut är redan hanterad"):
            self._as(self.internal_user).action_accept_close_request()

    def test_drag_to_avslutad_resolves_a_pending_request(self):
        self._as(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        request = self._fresh()
        self.assertFalse(request.close_request_pending)
        self.assertEqual(request.close_request_resolved_at, request.closed_date)

    def test_other_stage_changes_leave_the_request_pending(self):
        # Assigning a resource auto-moves the case to Resurs tilldelad.
        self._as(self.internal_user).write({"user_id": self.internal_user.id})
        request = self._fresh()
        self.assertEqual(request.stage_id, self._stage("Resurs tilldelad"))
        self.assertTrue(request.close_request_pending)

    def test_closing_without_a_request_stamps_nothing(self):
        other = create_maintenance_request(self.env, maintenance_team_id=self.team.id)
        other.with_user(self.internal_user).write({"stage_id": self.stage_avslutad.id})
        self.assertFalse(other.close_request_resolved_at)

    def test_case_moved_out_of_avslutad_accepts_a_new_request(self):
        self._as(self.internal_user).action_accept_close_request()
        self._as(self.internal_user).write({"stage_id": self.stage_vantar.id})
        self.assertIs(self._as(self.mimer_user).request_close_from_tenant(), True)
        self.assertTrue(self._fresh().close_request_pending)
