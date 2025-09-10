from odoo import fields, models
from ..constants import SEARCH_TYPES


class SearchFieldsMixin(models.AbstractModel):
    """Mixin for search functionality fields."""
    _name = 'maintenance.search.fields.mixin'
    _description = 'Search Fields Mixin'

    # Search inputs
    search_value = fields.Char("Search", store=True)
    search_type = fields.Selection(
        SEARCH_TYPES,
        string="Search Type",
        default="pnr",
        required=True,
        store=True,
    )

    # Search option fields (populated by handlers)
    property_option_id = fields.Many2one(
        "maintenance.property.option",
        string="Property Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    building_option_id = fields.Many2one(
        "maintenance.building.option",
        string="Building Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option",
        string="Rental Property Option Id",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    maintenance_unit_option_id = fields.Many2one(
        "maintenance.maintenance.unit.option",
        string="Maintenance Unit Option",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    tenant_option_id = fields.Many2one(
        "maintenance.tenant.option",
        string="Tenant",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    lease_option_id = fields.Many2one(
        "maintenance.lease.option",
        string="Lease",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )
    parking_space_option_id = fields.Many2one(
        "maintenance.parking.space.option",
        string="Parking Space",
        domain=lambda self: [("user_id", "=", self.env.user.id)],
        readonly=False,
    )