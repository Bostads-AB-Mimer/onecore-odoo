"""Tests for what this module contributes to a user onecore_auth creates at
their first Keycloak login (MIM-2010).

The hooks are called directly. That the user actually ends up with the values
is covered end to end in onecore_auth/tests/test_auto_create_user.py; what
matters here is this module's half of the contract.
"""
from odoo.tests import TransactionCase, tagged


# post_install: onecore_auth defines the other half of the hooks, and with the
# whole registry loaded the result does not depend on the module load order.
@tagged("onecore", "post_install", "-at_install")
class TestAutoCreateHooks(TransactionCase):
    def test_group_hook_adds_request_admin(self):
        """Without Admin Ärendehantering an internal user sees no requests."""
        group_ids = self.env["res.users"]._auto_create_group_ids()

        self.assertIn(self.env.ref("maintenance.group_equipment_manager").id, group_ids)

    def test_values_hook_sets_inbox_notifications(self):
        """Odoo's default is "By e-mail"; the "Olästa meddelanden" filter and
        the unread indicators only work for "In Odoo"."""
        values = self.env["res.users"]._auto_create_user_values({})

        self.assertEqual(values["notification_type"], "inbox")

    def test_relink_hook_adds_request_admin_for_an_employee_only(self):
        """Every mimer.nu account needs Admin Ärendehantering; the external
        contractors are the one group that works without it."""
        from ..utils.test_utils import (
            create_external_contractor_user,
            create_internal_user,
        )

        manager_id = self.env.ref("maintenance.group_equipment_manager").id
        employee = create_internal_user(self.env)
        contractor = create_external_contractor_user(self.env)
        Users = self.env["res.users"]

        self.assertIn(manager_id, Users._auto_relink_group_ids(employee))
        self.assertNotIn(manager_id, Users._auto_relink_group_ids(contractor))

    def test_hooks_merge_with_the_other_modules_contribution(self):
        """The hooks are cooperative (getattr(super()) rather than a plain
        override) because this module and onecore_auth do not depend on each
        other and may load in either order. Whatever the MRO turned out to
        be, nobody's contribution may be shadowed."""
        Users = self.env["res.users"]
        if "onecore_auth" not in self.env.registry._init_modules:
            self.skipTest("onecore_auth is not installed")

        group_ids = Users._auto_create_group_ids()
        values = Users._auto_create_user_values({})

        for group in Users._default_groups():
            self.assertIn(group.id, group_ids)
        self.assertIn(self.env.ref("maintenance.group_equipment_manager").id, group_ids)
        self.assertEqual(values["notification_type"], "inbox")
        self.assertEqual(values["tz"], "Europe/Stockholm")
