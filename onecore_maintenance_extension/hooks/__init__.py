"""Seeding of the OneCore maintenance stages.

Run from the post_init hook on install and from migrations/19.0.1.0.3 and
/19.0.1.0.4 on upgrade. Every path calls _update_maintenance_stages(), which
must be idempotent: it is re-run whenever a database replays an old migration.
_repair_duplicate_stages() is migration-only — a fresh install cannot end up
in the state it repairs.

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


def _foreign_xml_ids(env, stage, own_xml_id):
    """xml-ids pointing at this stage that are not ``own_xml_id``.

    A stage carrying someone else's xml-id belongs to that module — we neither
    merge it away nor move its requests.
    """
    module, name = own_xml_id.split(".", 1)
    return env["ir.model.data"].search(
        [
            ("model", "=", STAGE_MODEL),
            ("res_id", "=", stage.id),
            "!",
            "&",
            ("module", "=", module),
            ("name", "=", name),
        ]
    )


def _repair_duplicate_stages(env):
    """Merge stages that an earlier release duplicated. Safe to run repeatedly.

    _update_maintenance_stages() stops NEW duplicates, but it cannot heal a
    database where the previous version already made one: there the xml-id
    points at a freshly created (empty) stage while the original — carrying
    every historical request — sits orphaned under the same name. Resolving
    the xml-id succeeds, so nothing in the normal path ever looks further.

    The oldest record wins: it is the one request history hangs off. Losers
    hand over their requests, and are deleted only when they are fully
    detached (no xml-id of their own, no requests left). Anything unexpected
    is logged and skipped — a failed cleanup must never abort an upgrade.
    """
    Stage = env[STAGE_MODEL]

    for xml_id, stage_values in STAGE_DATA.items():
        name = stage_values["name"]
        try:
            duplicates = Stage.with_context(active_test=False).search(
                [("name", "=", name)], order="id"
            )
            if len(duplicates) < 2:
                continue

            survivor = duplicates[0]
            if _foreign_xml_ids(env, survivor, xml_id):
                _logger.warning(
                    "Not merging stages named %r: %s is owned by another "
                    "module",
                    name,
                    survivor.id,
                )
                continue

            # Only stages nothing else lays claim to may be merged away. A
            # duplicate carrying someone else's xml-id is their record, not a
            # leftover of ours.
            losers = duplicates[1:].filtered(
                lambda stage: not _foreign_xml_ids(env, stage, xml_id)
            )
            if not losers:
                _logger.warning(
                    "Duplicate stages named %r (%s) all belong to other "
                    "modules; leaving them alone",
                    name,
                    duplicates.ids,
                )
                continue

            _logger.warning(
                "Duplicate maintenance stages named %r (%s); merging %s into %s",
                name,
                duplicates.ids,
                losers.ids,
                survivor.id,
            )

            # Straight SQL, not write(): a stage change runs the workflow
            # rules (priority validation, team handback, chatter tracking) and
            # would raise on the first legacy request that never got a
            # priority. Nothing about the request actually changes here — the
            # two rows are the same stage, one of them by accident.
            env.cr.execute(
                "UPDATE maintenance_request SET stage_id = %s WHERE stage_id IN %s",
                (survivor.id, tuple(losers.ids)),
            )
            if env.cr.rowcount:
                _logger.info(
                    "Moved %s requests from stages %s to %s",
                    env.cr.rowcount,
                    losers.ids,
                    survivor.id,
                )
            env.invalidate_all()

            # Point our xml-id at the survivor before deleting anything, so a
            # failure below still leaves the database resolvable.
            _link_xml_id(env, xml_id, survivor)
            losers.unlink()
            _logger.info("Removed duplicate stages %s (%r)", losers.ids, name)
        except Exception:  # noqa: BLE001 - never block an upgrade on cleanup
            _logger.exception("Could not repair duplicate stages named %r", name)


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
