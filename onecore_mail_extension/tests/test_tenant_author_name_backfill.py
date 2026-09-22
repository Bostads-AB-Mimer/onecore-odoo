"""MIM-2040 — backfill of onecore_tenant_author_name over existing messages.

The label is captured when a message is created, so every message already in
the database would stay NULL forever without this one-off pass. Mina sidor
would then have nothing to show beside the whole of a tenant's history.
"""

import importlib.util
import os

from odoo import SUPERUSER_ID
from odoo.tests import TransactionCase, tagged


def _load_backfill_migration():
    """Load migrations/19.0.1.0.1/post-migration.py by path.

    The migration lives outside the importable package tree (the directory name
    is not a valid Python identifier), so it has to be loaded from its file
    location. Mirrors the idiom in onecore_maintenance_extension's
    tests/models/test_customer_message_indicator.py.
    """
    module_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(module_root, "migrations", "19.0.1.0.1", "post-migration.py")
    spec = importlib.util.spec_from_file_location("mim_2040_post_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore", "post_install", "-at_install")
class TestTenantAuthorNameBackfill(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.migration = _load_backfill_migration()
        category_id = cls.env.ref("onecore_maintenance_extension.category_1").id
        internal_group = cls.env.ref("base.group_user")
        manager_group = cls.env.ref("maintenance.group_equipment_manager")
        ext_group = cls.env.ref(
            "onecore_maintenance_extension.group_external_contractor"
        )
        cls.internal_user = cls.env["res.users"].create(
            {
                "name": "Sebastian Handläggare",
                "login": "internal_backfill_test",
                "group_ids": [(6, 0, [internal_group.id, manager_group.id])],
            }
        )
        cls.external_user = cls.env["res.users"].create(
            {
                "name": "Erika Entreprenör",
                "login": "ext_backfill_test",
                "group_ids": [(6, 0, [internal_group.id, ext_group.id])],
            }
        )
        cls.team = cls.env["maintenance.team"].create(
            {
                "name": "Städbolaget AB",
                "member_ids": [(6, 0, [cls.external_user.id])],
            }
        )
        cls.request = cls.env["maintenance.request"].create(
            {
                "name": "Trasig kran",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "hidden_from_my_pages": False,
                "maintenance_team_id": cls.team.id,
            }
        )

    def _legacy_message(self, author, message_type, author_name=None, record=None):
        """A message as prod holds it today: the right type, no author label.

        Created as a plain comment and then rewritten in SQL, so create()'s
        SMS/e-post dispatch is never involved — these stand in for rows written
        long before this field existed.
        """
        record = self.request if record is None else record
        message = self.env["mail.message"].create(
            {
                "model": "maintenance.request",
                "res_id": record.id,
                "body": "Gammalt meddelande",
                "message_type": "comment",
                "author_id": author.partner_id.id,
            }
        )
        self.env.cr.execute(
            """UPDATE mail_message
                  SET message_type = %s, onecore_tenant_author_name = %s
                WHERE id = %s""",
            (message_type, author_name, message.id),
        )
        self.env.invalidate_all()
        return message

    def _run(self):
        self.migration.backfill_tenant_author_names(self.env)
        self.env.invalidate_all()

    def test_internal_history_is_attributed_to_mimer(self):
        message = self._legacy_message(self.internal_user, "tenant_my_pages")
        self._run()
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_contractor_history_names_the_resource_group(self):
        message = self._legacy_message(self.external_user, "tenant_sms")
        self._run()
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Städbolaget AB"
        )

    def test_superuser_history_is_attributed_to_mimer(self):
        # OdooBot is a member of group_external_contractor (security/
        # maintenance.xml), so the backfill has to make the same exception the
        # write path does.
        root = self.env.ref("base.user_root")
        message = self._legacy_message(root, "tenant_mail")
        self._run()
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_failed_send_history_is_attributed(self):
        # The failed_*/partial types only ever exist in history — create()
        # rewrites into them — so the backfill must cover them even though the
        # write path never sees them as an incoming type.
        message = self._legacy_message(self.internal_user, "failed_tenant_mail")
        self._run()
        self.assertEqual(message.onecore_tenant_author_name, "Mimer")

    def test_tenant_written_history_is_left_alone(self):
        message = self._legacy_message(self.internal_user, "from_tenant")
        self._run()
        self.assertFalse(message.onecore_tenant_author_name)

    def test_internal_notes_are_left_alone(self):
        message = self._legacy_message(self.internal_user, "comment")
        self._run()
        self.assertFalse(message.onecore_tenant_author_name)

    def test_existing_labels_survive_a_rerun(self):
        # Migrations are re-run whenever an older database is upgraded through
        # this version; a second pass must not relabel a message whose sender
        # was already captured.
        message = self._legacy_message(
            self.external_user,
            "tenant_my_pages",
            author_name="Mimers Leverantör - Gammal grupp",
        )
        self._run()
        self.assertEqual(
            message.onecore_tenant_author_name, "Mimers Leverantör - Gammal grupp"
        )

    def test_superuser_partner_is_not_treated_as_a_contractor(self):
        # Guards the set the backfill builds, independently of the row-level
        # assertions above.
        partner_ids = self.migration.contractor_partner_ids(self.env)
        self.assertIn(self.external_user.partner_id.id, partner_ids)
        self.assertNotIn(
            self.env["res.users"].browse(SUPERUSER_ID).partner_id.id, partner_ids
        )

    def test_archived_resource_group_is_still_named(self):
        # A supplier whose contract has ended is archived, not deleted, and
        # maintenance.team has an `active` field — so search([]) would skip it
        # and freeze the bare label into exactly the history that is hardest to
        # recover. Rows are only ever filled in, so a re-run cannot repair it.
        category_id = self.env.ref("onecore_maintenance_extension.category_1").id
        team = self.env["maintenance.team"].create(
            {
                "name": "Utgången Leverantör AB",
                "member_ids": [(6, 0, [self.external_user.id])],
            }
        )
        request = self.env["maintenance.request"].create(
            {
                "name": "Gammalt ärende",
                "maintenance_request_category_id": category_id,
                "space_caption": "Lägenhet",
                "hidden_from_my_pages": False,
                "maintenance_team_id": team.id,
            }
        )
        message = self._legacy_message(self.external_user, "tenant_sms", record=request)
        team.active = False
        self._run()
        self.assertEqual(
            message.onecore_tenant_author_name,
            "Mimers Leverantör - Utgången Leverantör AB",
        )
