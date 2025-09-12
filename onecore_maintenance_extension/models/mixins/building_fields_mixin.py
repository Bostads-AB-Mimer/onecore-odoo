from odoo import fields, models


class BuildingFieldsMixin(models.AbstractModel):
    """Mixin for building-related fields."""
    _name = 'maintenance.building.fields.mixin'
    _description = 'Building Fields Mixin'

    building_id = fields.Many2one("maintenance.building", store=True, string="Byggnad")
    building_name = fields.Char("Byggnad", related="building_id.name", depends=["building_id"])
    building_code = fields.Char("Byggnadskod", related="building_id.code", depends=["building_id"])
    building_type_name = fields.Char("Byggnadstyp", related="building_id.building_type_name", depends=["building_id"])
    building_construction_year = fields.Char("Byggår", related="building_id.construction_year", depends=["building_id"])
    building_renovation_year = fields.Char("Renoveringsår", related="building_id.renovation_year", depends=["building_id"])