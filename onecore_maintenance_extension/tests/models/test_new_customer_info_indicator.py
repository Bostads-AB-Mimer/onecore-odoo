"""Tests for the "Ny kundinfo" notification (MIM-1844).

MIM-1960 split the channels: a Mina-sidor tenant message is now
"Meddelande från kund" (see test_customer_message_indicator.py). "Ny kundinfo"
means exactly what the name says: recently_added_tenant, a Mimer-internal
data-quality flag (tenant back-filled from the OneCore API). There is no
timestamp — the signal *is* the flag, so acknowledging it just clears it.
"""
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

    def test_tenant_message_does_not_raise_ny_kundinfo(self):
        # MIM-1960 split the channels: a Mina-sidor message is
        # "Meddelande från kund", not "Ny kundinfo". "Ny kundinfo ska röra att
        # kundinformation uppdateras."
        _post_customer_info(self.request, self.mimer_user, self.internal_user)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)
        self.assertFalse(self._refresh(self.external_user).has_unread_new_customer_info)

    def test_ack_clears_the_recently_added_tenant_flag(self):
        self.request.recently_added_tenant = True
        self.request.with_user(
            self.internal_user
        ).action_acknowledge_new_customer_info()
        self.assertFalse(self.request.recently_added_tenant)
        self.assertFalse(self._refresh(self.internal_user).has_unread_new_customer_info)

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
