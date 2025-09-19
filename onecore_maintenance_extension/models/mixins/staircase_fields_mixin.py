from odoo import fields, models


class StaircaseFieldsMixin(models.AbstractModel):
    """Mixin for staircase-related fields."""
    _name = 'maintenance.staircase.fields.mixin'
    _description = 'Staircase Fields Mixin'

    staircase_option_id = fields.Many2one("maintenance.staircase.option", store=True, string="Trappuppgång")
    staircase_id = fields.Many2one("maintenance.staircase", store=True, string="Trappuppgång")
    staircase_name = fields.Char("Trappuppgång", related="staircase_id.name", depends=["staircase_id"])
    staircase_code = fields.Char("Trappuppgångskod", related="staircase_id.code", depends=["staircase_id"])
    staircase_floor_plan = fields.Char("Våningsplan", related="staircase_id.floor_plan", depends=["staircase_id"])
    staircase_accessible_by_elevator = fields.Boolean("Tillgänglig med hiss", related="staircase_id.accessible_by_elevator", depends=["staircase_id"])
