from odoo import models, fields


class OnecoreMaintenanceFacilityOption(models.Model):
    _name = "maintenance.facility.option"
    _description = "Facility Option"

    user_id = fields.Many2one(
        "res.users", "Användare", default=lambda self: self.env.user
    )
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    type_name = fields.Char("Lokaltyp")
    type_code = fields.Char("Lokaltypskod")
    rental_type = fields.Char("Hyrestyp")
    area = fields.Char("Yta")
    building_code = fields.Char("Byggnadskod")
    building_name = fields.Char("Byggnad")
    property_code = fields.Char("Fastighetsnummer")
    property_name = fields.Char("Fastighet")


class OnecoreMaintenanceFacility(models.Model):
    _name = "maintenance.facility"
    _description = "Facility"

    rental_property_id = fields.Char(string="Hyresobjekt ID", store=True)
    name = fields.Char("Namn", required=True)
    code = fields.Char("Kod")
    type_name = fields.Char("Lokaltyp")
    type_code = fields.Char("Lokaltypskod")
    rental_type = fields.Char("Hyrestyp")
    area = fields.Char("Yta")
    building_code = fields.Char("Byggnadskod")
    building_name = fields.Char("Byggnad")
    property_code = fields.Char("Fastighetsnummer")
    property_name = fields.Char("Fastighet")
    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
