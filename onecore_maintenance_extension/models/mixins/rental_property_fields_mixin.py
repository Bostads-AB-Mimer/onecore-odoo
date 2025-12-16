from odoo import fields, models


class RentalPropertyFieldsMixin(models.AbstractModel):
    """Mixin for rental property-related fields."""
    _name = 'maintenance.rental.property.fields.mixin'
    _description = 'Rental Property Fields Mixin'

    rental_property_id = fields.Many2one("maintenance.rental.property", store=True, string="Hyresobjekt")
    rental_property_name = fields.Char("Hyresobjekt Namn", related="rental_property_id.name", depends=["rental_property_id"])
    address = fields.Char("Adress", related="rental_property_id.address", depends=["rental_property_id"])
    property_type = fields.Char("Fastighetstyp", related="rental_property_id.property_type", depends=["rental_property_id"])
    code = fields.Char("Kod", related="rental_property_id.code", depends=["rental_property_id"])
    type = fields.Char("Typ", related="rental_property_id.type", depends=["rental_property_id"])
    area = fields.Char("Yta", related="rental_property_id.area", depends=["rental_property_id"])
    entrance = fields.Char("Ingång", related="rental_property_id.entrance", depends=["rental_property_id"])
    floor = fields.Char("Våning", related="rental_property_id.floor", depends=["rental_property_id"])
    has_elevator = fields.Char("Hiss", related="rental_property_id.has_elevator", depends=["rental_property_id"])
    estate_code = fields.Char("Fastigehtsnummer", related="rental_property_id.estate_code", depends=["rental_property_id"])
    estate = fields.Char("Fastighet", related="rental_property_id.estate", depends=["rental_property_id"])
    building_code = fields.Char("Kvarterskod", related="rental_property_id.building_code", depends=["rental_property_id"])
    building = fields.Char("Kvarter", related="rental_property_id.building", depends=["rental_property_id"])
    