from odoo import models, fields

class OnecoreMaintenanceLeaseOption(models.Model):
    _name = 'maintenance.lease.option'
    _description = 'Lease Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    lease_number = fields.Char('Lease Number', required=True)
    lease_type = fields.Char('Type', required=True)
    lease_start_date = fields.Date('Lease Start Date', required=True)
    lease_end_date = fields.Date('Lease End Date')
    notice_given_by = fields.Char('Notice Given By')
    notice_date = fields.Date('Notice Date')
    notice_time_tenant = fields.Integer('Notice Time Tenant')
    preferred_move_out_date = fields.Date('Preferred Move Out Date')
    termination_date = fields.Date('Termination Date')
    contract_date = fields.Date('Contract Date', required=True)
    last_debit_date = fields.Date('Last Debit Date')
    approval_date = fields.Date('Approval Date')
    rental_property_option_id = fields.Many2one('maintenance.rental.property.option', string='Rental Property Option')
    tenants = fields.One2many('maintenance.tenant.option', 'id', string='Tenants')

class OnecoreMaintenanceLease(models.Model):
    _name = 'maintenance.lease'
    _description = 'Lease'

    name = fields.Char('name', required=True)
    lease_id = fields.Char(string='Lease Id', store=True, readonly=True)
    lease_number = fields.Char('Lease Number', required=True)
    lease_type = fields.Char('Type', required=True)
    lease_start_date = fields.Date('Lease Start Date', required=True)
    lease_end_date = fields.Date('Lease End Date')
    notice_given_by = fields.Char('Notice Given By')
    notice_date = fields.Date('Notice Date')
    notice_time_tenant = fields.Integer('Notice Time Tenant')
    preferred_move_out_date = fields.Date('Preferred Move Out Date')
    termination_date = fields.Date('Termination Date')
    contract_date = fields.Date('Contract Date', required=True)
    last_debit_date = fields.Date('Last Debit Date')
    approval_date = fields.Date('Approval Date')
