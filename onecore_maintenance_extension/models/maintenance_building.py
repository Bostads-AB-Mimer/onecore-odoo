from odoo import models, fields


class OnecoreMaintenanceBuildingOption(models.TransientModel):
    _name = "maintenance.building.option"
    _description = "building"

    building_id = fields.Char(string="Byggnads ID", store=True)
    name = fields.Char("Namn", required=True)
    address = fields.Char("Adress")
    code = fields.Char("Kod")

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)


class OnecoreMaintenanceBuilding(models.Model):
    _name = "maintenance.building"
    _description = "Building"

    building_id = fields.Char(string="Byggnads ID", store=True)
    name = fields.Char("Namn", required=True)
    address = fields.Char("Adress")
    code = fields.Char("Kod")

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)
