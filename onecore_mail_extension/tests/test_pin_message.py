from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("onecore", "post_install", "-at_install")
class TestPinMessage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Pin Test Partner"})
        cls.message = cls.env["mail.message"].create(
            {
                "model": "res.partner",
                "res_id": cls.partner.id,
                "body": "En notering",
                "message_type": "comment",
            }
        )
        ext_group = cls.env.ref(
            "onecore_maintenance_extension.group_external_contractor"
        )
        internal_group = cls.env.ref("base.group_user")
        # A dedicated internal user is used (rather than the raw TransactionCase
        # env, which runs as base.user_root) because maintenance.xml explicitly
        # adds user_root to group_external_contractor, so the default test env
        # is itself considered an external contractor for has_group() checks.
        cls.internal_user = cls.env["res.users"].create(
            {
                "name": "Intern Handläggare",
                "login": "internal_pin_test",
                "group_ids": [(6, 0, [internal_group.id])],
            }
        )
        cls.external_user = cls.env["res.users"].create(
            {
                "name": "Extern Entreprenör",
                "login": "ext_contractor_pin_test",
                "group_ids": [(6, 0, [internal_group.id, ext_group.id])],
            }
        )

    def test_toggle_pin_sets_and_clears(self):
        message = self.message.with_user(self.internal_user)
        result = message.action_toggle_pin()
        self.assertTrue(message.pinned_at)
        self.assertTrue(result["pinned_at"])
        self.assertEqual(message.pinned_by_id, self.internal_user)

        result = message.action_toggle_pin()
        self.assertFalse(message.pinned_at)
        self.assertFalse(result["pinned_at"])
        self.assertFalse(message.pinned_by_id)

    def test_toggle_pin_records_author_name(self):
        message = self.message.with_user(self.internal_user)
        message.action_toggle_pin()
        self.assertEqual(message.pinned_by_name, self.internal_user.name)

    def test_toggle_pin_denied_for_external_contractor(self):
        with self.assertRaises(AccessError):
            self.message.with_user(self.external_user).action_toggle_pin()

    def test_can_pin_flag(self):
        self.assertTrue(self.message.with_user(self.internal_user).can_pin)
        self.assertFalse(self.message.with_user(self.external_user).can_pin)
