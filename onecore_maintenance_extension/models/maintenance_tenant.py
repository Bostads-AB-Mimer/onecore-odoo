from odoo import api, models, fields

from .constants import LEASE_STATUS_LABELS


class OnecoreMaintenanceTenantOption(models.Model):
    _name = "maintenance.tenant.option"
    _description = "Tenant Option"
    _unaccent = True

    user_id = fields.Many2one(
        "res.users", "Användare", default=lambda self: self.env.user
    )
    name = fields.Char("Namn", required=True)
    contact_code = fields.Char("Kundnummer", required=True)
    contact_key = fields.Char("Kontakt", required=True, search=False)
    national_registration_number = fields.Char("Personnummer")
    phone_number = fields.Char("Telefonnummer")
    email_address = fields.Char("E-postadress")
    is_tenant = fields.Boolean("Är hyresgäst", default=True)
    special_attention = fields.Boolean(string="Viktig kundinfo", readonly=True)
    lease_option_id = fields.Many2one("maintenance.lease.option", string="Lease Option")

    @api.depends("name", "lease_option_id.lease_status")
    def _compute_display_name(self):
        """Show the lease status next to the name in the dropdown only.

        `name` stays the bare person name (the value that gets persisted onto
        the request and used in the SMS); the status label (e.g. "Gällande") is
        purely presentational so users can tell apart a person's several leases.
        """
        for option in self:
            status_label = (
                LEASE_STATUS_LABELS.get(option.lease_option_id.lease_status)
                if option.lease_option_id
                else None
            )
            option.display_name = (
                f"{option.name} ({status_label})" if status_label else option.name
            )


class OnecoreMaintenanceTenant(models.Model):
    _name = "maintenance.tenant"
    _description = "Tenant"
    _unaccent = True

    name = fields.Char("Namn", required=True)
    contact_code = fields.Char("Kundnummer", required=True)
    contact_key = fields.Char("Kontakt", required=True, search=False)
    national_registration_number = fields.Char("Personnummer")
    phone_number = fields.Char("Telefonnummer")
    email_address = fields.Char("E-postadress")
    is_tenant = fields.Boolean("Är hyresgäst", default=True)
    special_attention = fields.Boolean(string="Viktig kundinfo", readonly=True)

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )
