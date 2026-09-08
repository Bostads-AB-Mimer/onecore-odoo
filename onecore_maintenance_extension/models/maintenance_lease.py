from odoo import api, models, fields

from .constants import LEASE_STATUS_LABELS


class OnecoreMaintenanceLeaseOption(models.Model):
    _name = "maintenance.lease.option"
    _description = "Lease Option"
    _unaccent = True

    user_id = fields.Many2one("res.users", "User", default=lambda self: self.env.user)
    name = fields.Char("name", required=True)
    # OneCore's leaseId — the identity, distinct from name, which is a display
    # string with the status label appended (e.g. "<leaseId> (Gällande)").
    lease_id = fields.Char("Kontrakt ID")
    lease_number = fields.Char("Kontraktnummer", required=True)
    lease_type = fields.Char("Kontraktstyp", required=True)
    lease_status = fields.Integer("Status", default=3)
    lease_start_date = fields.Date("Startdatum")
    lease_end_date = fields.Date("Slutdatum")
    notice_given_by = fields.Char("Uppsägning gjord av")
    notice_date = fields.Date("Datum för uppsägning")
    notice_time_tenant = fields.Integer("Uppsägningstid för hyresgäst")
    preferred_move_out_date = fields.Date("Önskat utflyttningsdatum")
    termination_date = fields.Date("Uppsägningsdatum")
    contract_date = fields.Date("Kontraktsdatum")
    last_debit_date = fields.Date("Datum för senaste debitering")
    approval_date = fields.Date("Datum för godkännande")
    parking_space_option_id = fields.Many2one(
        "maintenance.parking.space.option", string="Parking Space Option"
    )
    rental_property_option_id = fields.Many2one(
        "maintenance.rental.property.option", string="Rental Property Option"
    )
    facility_option_id = fields.Many2one(
        "maintenance.facility.option", string="Facility Option"
    )
    tenants = fields.One2many("maintenance.tenant.option", "id", string="Hyresgäster")


class OnecoreMaintenanceLease(models.Model):
    _name = "maintenance.lease"
    _description = "Lease"
    _unaccent = True

    # Computed rather than a plain Char so it can never go stale like the
    # option's display name does (MIM-1954): sync_lease_status only ever
    # writes lease_status, and this recomputes from it automatically.
    name = fields.Char("Kontrakt", compute="_compute_name", store=True)
    lease_id = fields.Char(string="Kontrakt ID", store=True, readonly=True)
    lease_number = fields.Char("Kontraktnummer", required=True)
    lease_type = fields.Char("Kontraktstyp", required=True)
    lease_start_date = fields.Date("Startdatum")
    lease_end_date = fields.Date("Slutdatum")
    notice_given_by = fields.Char("Uppsägning gjord av")
    notice_date = fields.Date("Datum för uppsägning")
    notice_time_tenant = fields.Integer("Uppsägningstid för hyresgäst")
    preferred_move_out_date = fields.Date("Önskat utflyttningsdatum")
    termination_date = fields.Date("Uppsägningsdatum")
    contract_date = fields.Date("Kontraktsdatum")
    last_debit_date = fields.Date("Datum för senaste debitering")
    approval_date = fields.Date("Datum för godkännande")
    lease_status = fields.Integer("Status")

    lease_status_label = fields.Char(
        "Kontraktsstatus", compute="_compute_lease_status_label", store=True
    )

    maintenance_request_id = fields.Many2one(
        "maintenance.request", string="Maintenance Request", ondelete="cascade"
    )

    @api.depends("lease_status")
    def _compute_lease_status_label(self):
        for lease in self:
            lease.lease_status_label = LEASE_STATUS_LABELS.get(lease.lease_status)

    @api.depends("lease_id", "lease_status_label")
    def _compute_name(self):
        for lease in self:
            if lease.lease_id and lease.lease_status_label:
                lease.name = f"{lease.lease_id} ({lease.lease_status_label})"
            else:
                lease.name = lease.lease_id
