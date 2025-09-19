from odoo import models, fields


class OnecoreMaintenanceStaircaseOption(models.Model):
    _name = "maintenance.staircase.option"
    _description = "Staircase Option"

    # Core identification fields
    staircase_id = fields.Char(string="Trappuppgångs ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")

    # Features
    floor_plan = fields.Char("Våningsplan")
    accessible_by_elevator = fields.Boolean("Tillgänglig med hiss")

    # Relations
    building_option_id = fields.Many2one(
        "maintenance.building.option",
        string="Building Option",
        ondelete="cascade"
    )
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option",
        string="Rental Property Option",
        ondelete="cascade"
    )
    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)


class OnecoreMaintenanceStaircase(models.Model):
    _name = "maintenance.staircase"
    _description = "Staircase"

    # Core identification fields
    staircase_id = fields.Char(string="Trappuppgångs ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")

    # Features
    floor_plan = fields.Char("Våningsplan")
    accessible_by_elevator = fields.Boolean("Tillgänglig med hiss")

    # Relations
    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )