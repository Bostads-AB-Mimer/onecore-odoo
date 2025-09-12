from odoo import fields, models


class TenantFieldsMixin(models.AbstractModel):
    """Mixin for tenant-related fields."""
    _name = 'maintenance.tenant.fields.mixin'
    _description = 'Tenant Fields Mixin'

    tenant_id = fields.Many2one("maintenance.tenant", string="Hyresgäst ID", store=True)
    tenant_name = fields.Char("Namn", related="tenant_id.name", depends=["tenant_id"])
    contact_code = fields.Char("Kundnummer", related="tenant_id.contact_code", depends=["tenant_id"])
    national_registration_number = fields.Char(
        "Personnummer",
        related="tenant_id.national_registration_number",
        depends=["tenant_id"],
        groups="maintenance.group_equipment_manager",
    )
    phone_number = fields.Char("Telefonnummer", related="tenant_id.phone_number", depends=["tenant_id"], readonly=False)
    email_address = fields.Char("E-postadress", related="tenant_id.email_address", depends=["tenant_id"], readonly=False)
    is_tenant = fields.Boolean("Är hyresgäst", related="tenant_id.is_tenant", depends=["tenant_id"])
    special_attention = fields.Boolean("Viktig kundinfo", related="tenant_id.special_attention", depends=["tenant_id"])
    
    # Additional tenant-related fields
    recently_added_tenant = fields.Boolean(string="Recently added tenant", store=True, default=False)
    empty_tenant = fields.Boolean(string="No tenant", store=False, compute="_compute_empty_tenant")