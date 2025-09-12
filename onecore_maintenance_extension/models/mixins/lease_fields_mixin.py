from odoo import fields, models


class LeaseFieldsMixin(models.AbstractModel):
    """Mixin for lease-related fields."""
    _name = 'maintenance.lease.fields.mixin'
    _description = 'Lease Fields Mixin'

    lease_id = fields.Many2one("maintenance.lease", string="Lease id", store=True)
    lease_name = fields.Char("Kontrakt", related="lease_id.name", depends=["lease_id"])
    lease_type = fields.Char("Typ av kontrakt", related="lease_id.lease_type", depends=["lease_id"])
    contract_date = fields.Date("Kontraktsdatum", related="lease_id.contract_date", depends=["lease_id"])
    lease_start_date = fields.Date("Kontrakt Startdatum", related="lease_id.lease_start_date", depends=["lease_id"])
    lease_end_date = fields.Date("Kontrakt Slutdatum", related="lease_id.lease_end_date", depends=["lease_id"])