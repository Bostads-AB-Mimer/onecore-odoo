"""Tests for migrations/19.0.1.0.14/post-migration.py and the post_init hook.

owner_user_id is labelled "Beställare" in every installed language, not only
in en_US, where the field's string puts it; and the shipped favorites get the
names and grouping the business settled on, which the noupdate data file does
not apply to an existing database.

The database starts as prod does: Swedish active, stock maintenance's Swedish
label still on the field, the favorites under their first names.
"""

import importlib.util
import os

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ...hooks import _post_init_hook


def _load_migration():
    """Load migrations/19.0.1.0.14/post-migration.py by file path: migration
    directories are not valid package names."""
    module_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    path = os.path.join(module_root, "migrations", "19.0.1.0.14", "post-migration.py")
    spec = importlib.util.spec_from_file_location("orderer_label", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("onecore")
class TestOrdererLabelMigration(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["res.lang"]._activate_lang("sv_SE")
        self._set_swedish_label("Skapad av användare")

    def _set_swedish_label(self, label):
        field = self.env["ir.model.fields"]._get("maintenance.request", "owner_user_id")
        field.update_field_translations("field_description", {"sv_SE": label})
        self.env.registry.clear_cache("stable")

    def _label(self, lang):
        description = (
            self.env["maintenance.request"]
            .with_context(lang=lang)
            .fields_get(["owner_user_id"])
        )
        return description["owner_user_id"]["string"]

    def test_starts_from_the_stock_swedish_label(self):
        self.assertEqual(self._label("sv_SE"), "Skapad av användare")

    def test_migration_labels_the_orderer_in_every_language(self):
        migration = _load_migration()

        migration.migrate(self.env.cr, "19.0.1.0.13")
        migration.migrate(self.env.cr, "19.0.1.0.13")

        self.assertEqual(self._label("sv_SE"), "Beställare")
        self.assertEqual(self._label("en_US"), "Beställare")

    def test_install_hook_labels_the_orderer(self):
        _post_init_hook(self.env)

        self.assertEqual(self._label("sv_SE"), "Beställare")


# Names and grouping the favorites had before this migration.
OLD_FAVORITES = {
    "filter_my_kvv_areas": {"name": "Mina kvartersvärdsområden"},
    "filter_ordered_by_my_department_at_others": {
        "name": "Beställt av min avdelning hos andra – alla",
    },
    "filter_my_active_orders_by_team": {
        "name": "Beställt av min avdelning hos andra – aktiva per resursgrupp",
        "context": "{'group_by': ['maintenance_team_id', 'stage_id']}",
    },
    "filter_in_my_district_ordered_by_others": {
        "name": "I mitt distrikt, beställt av andra",
    },
}


@tagged("onecore")
class TestFavoritesMigration(TransactionCase):
    def setUp(self):
        super().setUp()
        for xml_name, vals in OLD_FAVORITES.items():
            self._favorite(xml_name).write(vals)

    def _favorite(self, xml_name):
        return self.env.ref(f"onecore_maintenance_extension.{xml_name}")

    def test_migration_renames_the_favorites(self):
        _load_migration().migrate(self.env.cr, "19.0.1.0.13")

        self.assertEqual(
            {xml_name: self._favorite(xml_name).name for xml_name in OLD_FAVORITES},
            {
                "filter_my_kvv_areas": "Mina inkomna ärenden",
                "filter_ordered_by_my_department_at_others": "Beställt av min enhet hos andra – alla",
                "filter_my_active_orders_by_team": "Beställt av min enhet hos andra – aktiva",
                "filter_in_my_district_ordered_by_others": "Beställt av andra på min enhet",
            },
        )

    def test_migration_groups_active_orders_per_status(self):
        _load_migration().migrate(self.env.cr, "19.0.1.0.13")

        favorite = self._favorite("filter_my_active_orders_by_team")
        self.assertEqual(favorite.context, "{'group_by': ['stage_id']}")

    def test_migration_skips_a_deleted_favorite(self):
        """Anyone may delete a shared favorite; the migration must not fail."""
        self._favorite("filter_my_kvv_areas").unlink()

        _load_migration().migrate(self.env.cr, "19.0.1.0.13")

        self.assertEqual(
            self._favorite("filter_ordered_by_my_department_at_others").name,
            "Beställt av min enhet hos andra – alla",
        )
