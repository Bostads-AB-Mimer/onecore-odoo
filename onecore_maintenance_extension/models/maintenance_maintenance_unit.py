from odoo import models, fields


class OnecoreMaintenanceMaintenanceUnitOption(models.Model):
    _name = "maintenance.maintenance.unit.option"
    _description = "Maintenance Unit Option"

    name = fields.Char("name", required=True)
    type = fields.Char("Utrymmestyp")
    code = fields.Char("Utrymmeskod", required=True)
    caption = fields.Char("Utrymme", required=True)
    property_option_id = fields.Many2one(
        "maintenance.property.option", string="Property Option"
    )
    building_option_id = fields.Many2one(
        "maintenance.building.option", string="Building Option"
    )
    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option", string="Rental Property Option"
    )


class OnecoreMaintenanceMaintenanceUnit(models.Model):
    _name = "maintenance.maintenance.unit"
    _description = "Maintenance Unit"

    name = fields.Char("name", required=True)
    type = fields.Char("Utrymmestyp")  # TODO vill vi nullable?
    caption = fields.Char("Utrymme", required=True)
    code = fields.Char("Utrymmeskod", required=True)

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
