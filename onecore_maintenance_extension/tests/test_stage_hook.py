"""Tests for _update_maintenance_stages (hooks/__init__.py).

The hook runs on install and again from migrations/19.0.1.0.3 whenever a
database replays that migration. It must never create a second set of stages,
and it must survive the two broken states seen in the wild:

* Odoo 19 dropped maintenance.stage_5/stage_6, so upgraded databases keep the
  "Utförd"/"Avslutad" records without an xml-id (this produced duplicate
  stages in dev on 2026-08-21).
* An xml-id can outlive its record, which made a module upgrade fail with
  'duplicate key ... ir_model_data_module_name_uniq_index'.
"""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..hooks import _repair_duplicate_stages, _update_maintenance_stages
from .utils.test_utils import create_maintenance_request

STAGE_MODEL = "maintenance.stage"


@tagged("onecore")
class TestMaintenanceStageHook(TransactionCase):
    def _stages_named(self, name):
        return self.env[STAGE_MODEL].search([("name", "=", name)])

    def _imd(self, xml_id):
        module, name = xml_id.split(".", 1)
        return self.env["ir.model.data"].search(
            [("module", "=", module), ("name", "=", name), ("model", "=", STAGE_MODEL)]
        )

    def test_rerun_is_idempotent(self):
        before = self.env[STAGE_MODEL].search([])
        _update_maintenance_stages(self.env)
        after = self.env[STAGE_MODEL].search([])
        self.assertEqual(after.ids, before.ids)

    def test_missing_xml_id_adopts_the_existing_stage(self):
        """The Odoo 19 case: record kept, xml-id gone. Must adopt, not add."""
        stage = self.env.ref("maintenance.stage_5")
        self._imd("maintenance.stage_5").unlink()

        _update_maintenance_stages(self.env)

        self.assertEqual(self._stages_named("Utförd"), stage, "duplicate created")
        self.assertEqual(self._imd("maintenance.stage_5").res_id, stage.id)

    def test_stale_xml_id_is_repointed_instead_of_duplicated(self):
        """An xml-id pointing at a deleted record must not make create() fail
        on the unique index — that is the module-update error."""
        stage = self.env.ref("maintenance.stage_6")
        missing_id = self.env[STAGE_MODEL].search([], order="id desc", limit=1).id + 1000
        self._imd("maintenance.stage_6").write({"res_id": missing_id})

        _update_maintenance_stages(self.env)

        self.assertEqual(self._stages_named("Avslutad"), stage, "duplicate created")
        self.assertEqual(self._imd("maintenance.stage_6").res_id, stage.id)

    def test_creates_stage_when_nothing_exists(self):
        atersand = self.env.ref("onecore_maintenance_extension.stage_atersand")
        self._imd("onecore_maintenance_extension.stage_atersand").unlink()
        atersand.unlink()

        _update_maintenance_stages(self.env)

        recreated = self._stages_named("Återsänd")
        self.assertEqual(len(recreated), 1)
        self.assertTrue(recreated.fold)
        self.assertEqual(recreated.sequence, 7)
        self.assertEqual(
            self._imd("onecore_maintenance_extension.stage_atersand").res_id,
            recreated.id,
        )

    def test_values_are_reasserted(self):
        stage = self.env.ref("maintenance.stage_6")
        stage.write({"done": False, "sequence": 99})

        _update_maintenance_stages(self.env)

        self.assertTrue(stage.done)
        self.assertEqual(stage.sequence, 6)


@tagged("onecore")
class TestDuplicateStageRepair(TransactionCase):
    """_repair_duplicate_stages: heal what 19.0.1.0.3 already broke.

    The hook stops new duplicates but cannot fix a database where the previous
    release made one — there the xml-id resolves fine, to an empty stage, while
    every historical request sits on an orphaned twin.
    """

    def _stages_named(self, name):
        return self.env[STAGE_MODEL].search([("name", "=", name)], order="id")

    def _imd(self, xml_id):
        module, name = xml_id.split(".", 1)
        return self.env["ir.model.data"].search(
            [("module", "=", module), ("name", "=", name), ("model", "=", STAGE_MODEL)]
        )

    def _break_stage_5(self):
        """Recreate the damage: a second "Utförd" holding the xml-id, the
        original orphaned but still carrying the requests."""
        original = self.env.ref("maintenance.stage_5")
        duplicate = self.env[STAGE_MODEL].create(
            {"name": "Utförd", "sequence": 5, "done": False}
        )
        self._imd("maintenance.stage_5").write({"res_id": duplicate.id})
        return original, duplicate

    def _put_on_stage(self, request, stage):
        """Park a request on a stage the way history did, not the way the form
        allows: write() runs the workflow rules ("Utförd" demands a resource),
        which is precisely why the repair moves requests in SQL."""
        self.env.cr.execute(
            "UPDATE maintenance_request SET stage_id = %s WHERE id = %s",
            (stage.id, request.id),
        )
        request.invalidate_recordset(["stage_id"])

    def test_requests_survive_the_merge(self):
        original, duplicate = self._break_stage_5()
        request = create_maintenance_request(self.env)
        self._put_on_stage(request, original)

        _repair_duplicate_stages(self.env)

        self.assertEqual(self._stages_named("Utförd"), original, "duplicate kept")
        self.assertEqual(self._imd("maintenance.stage_5").res_id, original.id)
        self.assertEqual(request.stage_id, original)
        self.assertFalse(duplicate.exists())

    def test_requests_on_the_duplicate_are_moved(self):
        original, duplicate = self._break_stage_5()
        request = create_maintenance_request(self.env)
        self._put_on_stage(request, duplicate)

        _repair_duplicate_stages(self.env)

        self.assertEqual(request.stage_id, original)
        self.assertFalse(duplicate.exists())

    def test_healthy_database_is_untouched(self):
        before = self.env[STAGE_MODEL].search([]).ids

        _repair_duplicate_stages(self.env)

        self.assertEqual(self.env[STAGE_MODEL].search([]).ids, before)
        self.assertEqual(
            self._imd("maintenance.stage_5").res_id,
            self.env.ref("maintenance.stage_5").id,
        )

    def test_duplicate_owned_by_another_module_is_left_alone(self):
        """Someone else's record is not ours to merge away."""
        original, duplicate = self._break_stage_5()
        self.env["ir.model.data"].create(
            {
                "name": "stage_utford_other",
                "module": "base",
                "model": STAGE_MODEL,
                "res_id": duplicate.id,
                "noupdate": True,
            }
        )

        _repair_duplicate_stages(self.env)

        self.assertTrue(duplicate.exists())
        self.assertEqual(len(self._stages_named("Utförd")), 2)

    def test_repair_is_idempotent(self):
        self._break_stage_5()

        _repair_duplicate_stages(self.env)
        after_first = self.env[STAGE_MODEL].search([]).ids
        _repair_duplicate_stages(self.env)

        self.assertEqual(self.env[STAGE_MODEL].search([]).ids, after_first)
