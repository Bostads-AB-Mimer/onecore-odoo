from odoo import fields, models


class MaintenanceUnitFieldsMixin(models.AbstractModel):
    """Mixin for maintenance unit-related fields."""
    _name = 'maintenance.maintenance.unit.fields.mixin'
    _description = 'Maintenance Unit Fields Mixin'

    maintenance_unit_id = fields.Many2one("maintenance.maintenance.unit", string="Maintenance Unit ID", store=True)
    maintenance_unit_type = fields.Char("Utrymmestyp", related="maintenance_unit_id.type", depends=["maintenance_unit_id"])
    maintenance_unit_code = fields.Char("Utrymmeskod", related="maintenance_unit_id.code", depends=["maintenance_unit_id"])
    maintenance_unit_caption = fields.Char("Utrymme", related="maintenance_unit_id.caption", depends=["maintenance_unit_id"])