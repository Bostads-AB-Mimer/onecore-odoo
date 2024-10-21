from odoo import models, fields

class OnecoreMaintenanceTenantOption(models.Model):
    _name = 'maintenance.tenant.option'
    _description = 'Tenant Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    contact_code = fields.Char('Contact Code', required=True)
    contact_key = fields.Char('Contact Key', required=True)
    national_registration_number = fields.Char('National Registration Number', required=True)
    phone_number = fields.Char('Phone Number')
    email_address = fields.Char('Email Address')
    is_tenant = fields.Boolean('Is Tenant', default=True)

class OnecoreMaintenanceTenant(models.Model):
    _name = 'maintenance.tenant'
    _description = 'Tenant'

    name = fields.Char('name', required=True)
    contact_code = fields.Char('Contact Code', required=True)
    contact_key = fields.Char('Contact Key', required=True)
    national_registration_number = fields.Char('National Registration Number', required=True)
    phone_number = fields.Char('Phone Number')
    email_address = fields.Char('Email Address')
    is_tenant = fields.Boolean('Is Tenant', default=True)
