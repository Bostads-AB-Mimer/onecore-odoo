"""Tests for the "Meddelande från kund" signal (MIM-1960).

The tenant -> case channel is detected by message_type = 'from_tenant', the
value onecore's work-order service writes when it forwards a Mina-sidor
message. Acknowledgement is shared within each audience and split between them,
mirroring action_acknowledge_dialog.
"""

from odoo.tests.common import TransactionCase
from odoo.tests import tagged

from ..utils.test_utils import (
    create_internal_user,
    create_external_contractor_user,
    create_maintenance_request,
)


def _get_or_create_mimer_user(env):
    """The integration account the work-order service posts as."""
    user = env["res.users"].sudo().search([("login", "=", "odoo@mimer.nu")], limit=1)
    if not user:
        user = (
            env["res.users"]
            .sudo()
            .create(
                {
                    "name": "Mimer Integration",
                    "login": "odoo@mimer.nu",
                    # message_post() writes a mail.message tied to the request,
                    # which needs write access on maintenance.request. Mirror
                    # the internal-handler groups so the team record rule lets
                    # the post through (base.group_user alone fails it).
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
        )
    return user


def _post_tenant_message(
    request, mimer_user, body="Hur går det?", message_type="from_tenant"
):
    """Post exactly as odoo-adapter.addMessageToWorkOrder does: message_post
    with message_type='from_tenant' and the default note subtype."""
    return request.with_user(mimer_user).message_post(
        body=body, message_type=message_type
    )


class CustomerMessageCase(TransactionCase):
    """Shared fixture: an internal user, a contractor on the request's team.

    The external-contractor record rule (security/maintenance.xml) only grants
    access to requests on the contractor's own team.
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


@tagged("onecore")
class TestLastCustomerMessageAt(CustomerMessageCase):
    def test_from_tenant_message_sets_the_timestamp(self):
        message = _post_tenant_message(self.request, self.mimer_user)
        self.assertEqual(self.request.last_customer_message_at, message.date)

    def test_newer_message_moves_the_timestamp_forward(self):
        _post_tenant_message(self.request, self.mimer_user)
        second = _post_tenant_message(self.request, self.mimer_user, body="Igen")
        self.assertEqual(self.request.last_customer_message_at, second.date)

    def test_other_message_types_are_ignored(self):
        _post_tenant_message(self.request, self.mimer_user, message_type="comment")
        self.assertFalse(self.request.last_customer_message_at)

    def test_no_message_means_no_timestamp(self):
        self.assertFalse(self.request.last_customer_message_at)

    def test_the_write_logs_no_audit_note(self):
        # The request is written on every inbound tenant message. Without a
        # SKIP_FIELDS entry, FieldChangeTracker posts a chatter note about the
        # field change on top of the tenant's own message.
        #
        # create_maintenance_request()/create() leaves `creating_records=True`
        # on the returned recordset's context (see maintenance.py create()),
        # which makes write() skip FieldChangeTracker entirely. Tests that
        # assert on posted chatter notes must override it, same as
        # test_new_customer_info_indicator.py, test_master_key_change_indicator.py
        # and test_maintenance_workflow_service.py do.
        request = self.request.with_context(creating_records=False)
        before = set(request.message_ids.ids)
        _post_tenant_message(request, self.mimer_user)
        # message_ids is a plain relational field, not a compute — it was
        # already fetched (and cached) by the `before` read above, so it must
        # be explicitly invalidated to see the note just posted.
        request.invalidate_recordset(["message_ids"])
        new_bodies = " ".join(
            request.message_ids.filtered(lambda m: m.id not in before).mapped("body")
        )
        # Assert on the field LABEL: FieldChangeTracker logs labels, never
        # field names. Asserting on the name would pass even with the
        # SKIP_FIELDS entry removed.
        self.assertNotIn("Senaste meddelande från kund", new_bodies)


@tagged("onecore")
class TestAckColumnRename(CustomerMessageCase):
    """The MIM-1844 ack pair is renamed, not duplicated: it only ever served
    the Mina-sidor channel, so its values carry over verbatim and MIM-1844's
    cutover baseline stays valid."""

    def test_new_names_exist(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("customer_message_ack_at", fields_)
        self.assertIn("customer_message_external_ack_at", fields_)

    def test_old_names_are_gone(self):
        fields_ = self.env["maintenance.request"]._fields
        self.assertNotIn("new_customer_info_ack_at", fields_)
        self.assertNotIn("new_customer_info_external_ack_at", fields_)

    def test_labels_are_swedish_so_acks_reach_the_audit_log(self):
        # FieldChangeTracker logs by field label; a missing/English label would
        # silently drop the acknowledgement from the chatter.
        fields_ = self.env["maintenance.request"]._fields
        self.assertIn("kund", fields_["customer_message_ack_at"].string.lower())
        self.assertIn(
            "entreprenör",
            fields_["customer_message_external_ack_at"].string.lower(),
        )
