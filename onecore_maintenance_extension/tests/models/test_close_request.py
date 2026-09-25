"""Tests for the tenant's close request (MIM-2036).

A tenant can no longer close an Odoo case from Mina sidor. They ask, via
request_close_from_tenant, and an Odoo user decides: "Avsluta ärendet"
(action_accept_close_request) or "Avslå" with a reason (the decline wizard).
Moving the case to Avslutad any other way also resolves the request.
"""

from datetime import timedelta

from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

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
