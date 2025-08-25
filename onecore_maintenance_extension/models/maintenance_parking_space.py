from odoo import models, fields


class OnecoreMaintenanceParkingSpaceOption(models.Model):
    _name = "maintenance.parking.space.option"
    _description = "Parking Space Option"

    user_id = fields.Many2one(
        "res.users", "Användare", default=lambda self: self.env.user
    )
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    type_name = fields.Char("P-platstyp")
    type_code = fields.Char("P-platstypkod")
    number = fields.Char("P-platsnummer")
    property_code = fields.Char("Fastighetskod")
    property_name = fields.Char("Fastighet")
    address = fields.Char("Adress")
    postal_code = fields.Char("Postnummer")
    city = fields.Char("Stad")


class OnecoreMaintenanceParkingSpace(models.Model):
    _name = "maintenance.parking.space"
    _description = "Parking Space"

    rental_property_id = fields.Char(string="Hyresobjekt ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    type_name = fields.Char("P-platstyp")
    type_code = fields.Char("P-platstypkod")
    number = fields.Char("P-platsnummer")
    property_code = fields.Char("Fastighetskod")
    property_name = fields.Char("Fastighet")
    address = fields.Char("Adress")
    postal_code = fields.Char("Postnummer")
    city = fields.Char("Stad")
    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
