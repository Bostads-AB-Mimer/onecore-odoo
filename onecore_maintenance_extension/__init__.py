# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import models

def _maintenance_stage_update_hook(env):
    stage_data = {
        'stage_0': {'name': 'Väntar på handläggning', 'fold': False, 'done': False, 'sequence': 1},
        'stage_1': {'name': 'Resurs tilldelad', 'fold': False, 'done': False, 'sequence': 2},
        'stage_3': {'name': 'Påbörjad', 'fold': False, 'done': False, 'sequence': 3},
        'stage_4': {'name': 'Väntar på beställda varor', 'fold': False, 'done': False, 'sequence': 4},
        'stage_5': {'name': 'Avslutad', 'fold': True, 'done': True, 'sequence': 5},
    }

    existing_stages = env['maintenance.stage'].search([])

    # Update existing stages
    for stage in existing_stages:
        xml_id = env['ir.model.data'].search([('res_id', '=', stage.id), ('model', '=', 'maintenance.stage')]).name
        if xml_id in stage_data:
            stage.write(stage_data[xml_id])
            stage.with_context(lang='sv_SE').write(stage_data[xml_id])
            del stage_data[xml_id]

    # Add new stages
    for xml_id, stage_values in stage_data.items():
        new_stage = env['maintenance.stage'].create(stage_values)
        env['ir.model.data'].create({
            'name': xml_id,
            'model': 'maintenance.stage',
            'module': 'maintenance',
            'res_id': stage.id,
        })
        new_stage.with_context(lang='sv_SE').write({'name': stage_values['name']})
