from odoo import fields
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

    def test_external_contractor_can_pin(self):
        # Everyone may pin now, including external contractors (see
        # mail.message._user_can_pin — the single gate for this).
        message = self.message.with_user(self.external_user)
        result = message.action_toggle_pin()
        self.assertTrue(message.pinned_at)
        self.assertTrue(result["pinned_at"])
        self.assertEqual(message.pinned_by_id, self.external_user)

    def test_can_pin_flag_true_for_everyone(self):
        self.assertTrue(self.message.with_user(self.internal_user).can_pin)
        self.assertTrue(self.message.with_user(self.external_user).can_pin)

    def test_fetch_pinned_messages_returns_all_regardless_of_recency(self):
        # The chatter paginates on the 30 most recent messages (MIM-1301
        # review). _fetch_pinned_messages queries by pinned_at with no limit so
        # a note pinned before that window still surfaces in the "Fästa"
        # section without the user scrolling to load it.
        Message = self.env["mail.message"]
        old_pinned = Message.create(
            {
                "model": "res.partner",
                "res_id": self.partner.id,
                "body": "Gammal fäst notering",
                "message_type": "comment",
                "pinned_at": fields.Datetime.now(),
            }
        )
        # Bury it well past the chatter's 30-message pagination window.
        for i in range(35):
            Message.create(
                {
                    "model": "res.partner",
                    "res_id": self.partner.id,
                    "body": f"Notering {i}",
                    "message_type": "comment",
                }
            )

        pinned = Message._fetch_pinned_messages(self.partner)

        self.assertIn(old_pinned, pinned)
        self.assertTrue(all(m.pinned_at for m in pinned))

    def test_fetch_pinned_messages_scoped_to_thread(self):
        # Pinned messages on other records must not leak into this thread's
        # "Fästa" section.
        Message = self.env["mail.message"]
        other_partner = self.env["res.partner"].create({"name": "Annan"})
        Message.create(
            {
                "model": "res.partner",
                "res_id": other_partner.id,
                "body": "Fäst på annan post",
                "message_type": "comment",
                "pinned_at": fields.Datetime.now(),
            }
        )
        this_pinned = Message.create(
            {
                "model": "res.partner",
                "res_id": self.partner.id,
                "body": "Fäst här",
                "message_type": "comment",
                "pinned_at": fields.Datetime.now(),
            }
        )

        pinned = Message._fetch_pinned_messages(self.partner)

        self.assertEqual(pinned, this_pinned)
