from odoo import models, fields


class OnecoreMaintenanceMaintenanceUnitOption(models.Model):
    _name = "maintenance.maintenance.unit.option"
    _description = "Maintenance Unit Option"

    name = fields.Char("name", required=True)
    type = fields.Char("Utrymmestyp", required=True)
    code = fields.Char("Utrymmeskod", required=True)
    caption = fields.Char("Utrymme", required=True)
    estate_code = fields.Char("Fastighetskod", required=True)
    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option", string="Rental Property Option"
    )


class OnecoreMaintenanceMaintenanceUnit(models.Model):
    _name = "maintenance.maintenance.unit"
    _description = "Maintenance Unit"

    name = fields.Char("name", required=True)
    type = fields.Char("Utrymmestyp", required=True)
    caption = fields.Char("Utrymme", required=True)
    code = fields.Char("Utrymmeskod", required=True)
    estate_code = fields.Char("Fastighetskod", required=True)
