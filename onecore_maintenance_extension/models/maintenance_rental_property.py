from odoo import models, fields


class OnecoreMaintenanceRentalPropertyOption(models.Model):
    _name = "maintenance.rental.property.option"
    _description = "Rental Property Option"

    user_id = fields.Many2one(
        "res.users", "Användare", default=lambda self: self.env.user
    )
    name = fields.Char("Namn", required=True)
    property_type = fields.Char("Fastighetstyp", required=True)
    address = fields.Char("Adress")
    code = fields.Char("Kod")
    type = fields.Char("Typ")
    area = fields.Char("Yta")
    entrance = fields.Char("Ingång")
    floor = fields.Char("Våning")
    has_elevator = fields.Char("Hiss")
    wash_space = fields.Char("Tvättutrymme")
    estate_code = fields.Char("Fastighetskod")
    estate = fields.Char("Fastighet")
    building_code = fields.Char("Kvarterskod")
    building = fields.Char("Kvarter")
    lease_ids = fields.One2many(
        "maintenance.lease.option", "rental_property_option_id", string="Leases"
    )
    maintenance_unit_ids = fields.One2many(
        "maintenance.maintenance.unit.option",
        "rental_property_option_id",
        string="Maintenance Units Options",
    )


class OnecoreMaintenanceRentalProperty(models.Model):
    _name = "maintenance.rental.property"
    _description = "Rental Property"

    rental_property_id = fields.Char(string="Hyresobjekt ID", store=True)
    name = fields.Char("Namn", required=True)
    property_type = fields.Char("Fastighetstyp", required=True)
    address = fields.Char("Adress")
    code = fields.Char("Kod")
    type = fields.Char("Typ")
    area = fields.Char("Yta")
    entrance = fields.Char("Ingång")
    floor = fields.Char("Våning")
    has_elevator = fields.Char("Hiss")
    wash_space = fields.Char("Tvättutrymme")
    estate_code = fields.Char("Fastighetskod")
    estate = fields.Char("Fastighet")
    building_code = fields.Char("Kvarterskod")
    building = fields.Char("Kvarter")
