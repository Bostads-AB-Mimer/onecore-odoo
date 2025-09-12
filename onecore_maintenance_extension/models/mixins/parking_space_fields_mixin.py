from odoo import fields, models


class ParkingSpaceFieldsMixin(models.AbstractModel):
    """Mixin for parking space-related fields."""
    _name = 'maintenance.parking.space.fields.mixin'
    _description = 'Parking Space Fields Mixin'

    parking_space_id = fields.Many2one("maintenance.parking.space", string="Parking Space ID", store=True)
    parking_space_name = fields.Char("P-plats Namn", related="parking_space_id.name", depends=["parking_space_id"])
    parking_space_code = fields.Char("P-plats Kod", related="parking_space_id.code", depends=["parking_space_id"])
    parking_space_type_name = fields.Char("P-platstyp", related="parking_space_id.type_name", depends=["parking_space_id"])
    parking_space_type_code = fields.Char("P-platstypkod", related="parking_space_id.type_code", depends=["parking_space_id"])
    parking_space_number = fields.Char("P-platsnummer", related="parking_space_id.number", depends=["parking_space_id"])
    parking_space_property_code = fields.Char("P-plats Fastighetskod", related="parking_space_id.property_code", depends=["parking_space_id"])
    parking_space_property_name = fields.Char("P-plats Fastighet", related="parking_space_id.property_name", depends=["parking_space_id"])
    parking_space_address = fields.Char("P-plats Adress", related="parking_space_id.address", depends=["parking_space_id"])
    parking_space_postal_code = fields.Char("P-plats Postnummer", related="parking_space_id.postal_code", depends=["parking_space_id"])
    parking_space_city = fields.Char("P-plats Stad", related="parking_space_id.city", depends=["parking_space_id"])