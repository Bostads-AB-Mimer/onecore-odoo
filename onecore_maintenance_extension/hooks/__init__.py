def _post_init_hook(env):
    _update_maintenance_stages(env)


def _has_lang(env, lang_code):
    """Check if a language is installed and active."""
    return bool(env['res.lang']._get_data(code=lang_code))


def _update_maintenance_stages(env):
    sv_installed = _has_lang(env, 'sv_SE')

    stage_data = {
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

    existing_stages = env["maintenance.stage"].search([])

    # Update existing stages
    # We need to update the existing stages first to keep the stage ids for the new stages
    for stage in existing_stages:
        imd = env["ir.model.data"].search(
            [("res_id", "=", stage.id), ("model", "=", "maintenance.stage")],
            limit=1,
        )
        xml_id = f"{imd.module}.{imd.name}" if imd else None
        if xml_id in stage_data:
            stage.write(stage_data[xml_id])
            if sv_installed:
                stage.with_context(lang="sv_SE").write(stage_data[xml_id])
            del stage_data[xml_id]

    # Add new stages
    for xml_id, stage_values in stage_data.items():
        module, name = xml_id.split(".", 1)
        new_stage = env["maintenance.stage"].create(stage_values)
        env["ir.model.data"].create(
            {
                "name": name,
                "model": "maintenance.stage",
                "module": module,
                "res_id": new_stage.id,
                # Without noupdate, ir.model.data._process_end deletes the
                # xml-id and its record on the next upgrade of the module.
                "noupdate": True,
            }
        )
        if sv_installed:
            new_stage.with_context(lang="sv_SE").write({"name": stage_values["name"]})
