"""Regression tests for MIM-1768 — auto-follower bug after Odoo 19 upgrade.

The bug fires when a `mail.message.subtype` has both `res_model='maintenance.request'`
and `relation_field` set. Odoo 19 (commit 78168325708) reads `relation_field`
unconditionally in `_get_auto_subscription_subtypes`, which makes
`_message_auto_subscribe` treat the `user_id` value as if it were a
`maintenance.request.id` and copy the followers of that arbitrary ticket onto
every newly created/updated ticket.

The fix removes `relation_field` from `mt_from_tenant` (the subtype that had it).
"""
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("onecore", "mim_1768")
class TestMimFromTenantSubtype(TransactionCase):
    """Guard against the relation_field misconfiguration regressing on the
    `mt_from_tenant` subtype."""

    def test_mt_from_tenant_relation_field_is_unset(self):
        subtype = self.env.ref(
            "onecore_maintenance_extension.mt_from_tenant"
        )
        self.assertFalse(
            subtype.relation_field,
            "mt_from_tenant must NOT have relation_field set — see MIM-1768. "
            "Setting relation_field on a same-model subtype causes Odoo 19 to "
            "treat user_id values as maintenance.request ids and subscribe the "
            "followers of an arbitrary ticket onto every new ticket.",
        )
