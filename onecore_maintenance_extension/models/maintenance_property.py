from odoo import models, fields


class OnecoreMaintenancePropertyOption(models.TransientModel):
    _name = "maintenance.property.option"
    _description = "Property"
    _rec_name = "designation"

    code = fields.Char("Kod", required=True)
    designation = fields.Char("Beteckning", required=True)

    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)


class OnecoreMaintenanceProperty(models.Model):
    _name = "maintenance.property"
    _description = "Property"
    _rec_name = "designation"

    code = fields.Char("Kod", required=True)
    designation = fields.Char("Beteckning", required=True)

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
