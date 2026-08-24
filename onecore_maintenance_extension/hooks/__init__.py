"""Seeding of the OneCore maintenance stages.

Run from the post_init hook on install and from migrations/19.0.1.0.3 on
upgrade. Both paths call _update_maintenance_stages(), which must be
idempotent: it is re-run whenever a database replays an old migration.

Odoo 19 ships only stage_0, stage_1, stage_3 and stage_4 — stage_5/stage_6
existed in earlier versions. Databases upgraded to 19 therefore keep the
"Utförd"/"Avslutad" records while losing their xml-ids, so this module must
adopt what it finds instead of creating a second set of stages.
"""

import logging

_logger = logging.getLogger(__name__)

STAGE_MODEL = "maintenance.stage"

STAGE_DATA = {
    "maintenance.stage_0": {
        "name": "Väntar på handläggning",
        "fold": False,
        "done": False,
        "sequence": 1,
    },
    "maintenance.stage_1": {
        "name": "Resurs tilldelad",
        "fold": False,
        "done": False,
        "sequence": 2,
    },
    "maintenance.stage_3": {
        "name": "Påbörjad",
        "fold": False,
        "done": False,
        "sequence": 3,
    },
    "maintenance.stage_4": {
        "name": "Väntar på beställda varor",
        "fold": False,
        "done": False,
        "sequence": 4,
    },
    # Not shipped by Odoo 19 — created and owned by us, but kept under the
    # maintenance.* xml-ids that upgraded databases (and production) already
    # carry. Renaming them now would create a second set of stages.
    "maintenance.stage_5": {
        "name": "Utförd",
        "fold": False,
        "done": False,
        "sequence": 5,
    },
    "maintenance.stage_6": {
        "name": "Avslutad",
        "fold": False,
        "done": True,
        "sequence": 6,
    },
    # MIM-486: stage for requests returned/rejected by external
    # contractors. Folded in kanban for all users.
    "onecore_maintenance_extension.stage_atersand": {
        "name": "Återsänd",
        "fold": True,
        "done": False,
        "sequence": 7,
    },
}


def _post_init_hook(env):
    _update_maintenance_stages(env)


def _has_lang(env, lang_code):
    """Check if a language is installed and active."""
    return bool(env['res.lang']._get_data(code=lang_code))


def _stage_xml_id_row(env, xml_id):
    """The ir.model.data row for xml_id, queried directly.

    Deliberately not env.ref: that goes through an ormcache which can hand
    back a previously resolved id in a warm process, hiding the very state we
    are here to repair.
    """
    module, name = xml_id.split(".", 1)
    return env["ir.model.data"].search(
        [("module", "=", module), ("name", "=", name), ("model", "=", STAGE_MODEL)],
        limit=1,
    )


def _resolve_stage(env, xml_id):
    """The stage behind xml_id, or an empty recordset.

    The xml-id can outlive its record; creating a new one in that state
    raises ir_model_data_module_name_uniq_index, hence the exists() guard.
    """
    imd = _stage_xml_id_row(env, xml_id)
    stage = env[STAGE_MODEL].browse(imd.res_id) if imd else env[STAGE_MODEL].browse()
    return stage if stage.exists() else env[STAGE_MODEL].browse()


def _adopt_stage_by_name(env, name):
    """An existing stage with this name that no xml-id points at.

    This is the Odoo 19 case: the record survived the upgrade, its xml-id did
    not. Adopting it keeps request history intact — creating a new stage would
    leave every old request on an orphaned duplicate.
    """
    candidates = env[STAGE_MODEL].search([("name", "=", name)], order="id")
    for stage in candidates:
        linked = env["ir.model.data"].search_count(
            [("model", "=", STAGE_MODEL), ("res_id", "=", stage.id)]
        )
        if not linked:
            if len(candidates) > 1:
                _logger.warning(
                    "Several maintenance stages named %r (%s); adopting %s",
                    name,
                    candidates.ids,
                    stage.id,
                )
            return stage
    return env[STAGE_MODEL].browse()


def _link_xml_id(env, xml_id, stage):
    """Point xml_id at stage, reusing a stale row rather than creating a
    duplicate key."""
    module, name = xml_id.split(".", 1)
    imd = _stage_xml_id_row(env, xml_id)
    if imd:
        imd.write({"res_id": stage.id, "noupdate": True})
        return
    env["ir.model.data"].create(
        {
            "name": name,
            "model": STAGE_MODEL,
            "module": module,
            "res_id": stage.id,
            # Without noupdate, ir.model.data._process_end deletes the
            # xml-id and its record on the next upgrade of the module.
            "noupdate": True,
        }
    )


def _update_maintenance_stages(env):
    """Create or re-assert the OneCore stages. Safe to run repeatedly."""
    sv_installed = _has_lang(env, 'sv_SE')

    for xml_id, stage_values in STAGE_DATA.items():
        stage = _resolve_stage(env, xml_id)
        if not stage:
            stage = _adopt_stage_by_name(env, stage_values["name"])
            if stage:
                _logger.info("Adopting existing stage %s as %s", stage.id, xml_id)
                _link_xml_id(env, xml_id, stage)
        if not stage:
            stage = env[STAGE_MODEL].create(stage_values)
            _link_xml_id(env, xml_id, stage)

        stage.write(stage_values)
        if sv_installed:
            stage.with_context(lang="sv_SE").write(stage_values)
