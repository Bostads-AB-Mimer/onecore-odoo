from odoo import models, fields

class OnecoreMaintenanceTenantOption(models.Model):
    _name = 'maintenance.tenant.option'
    _description = 'Tenant Option'

    user_id = fields.Many2one('res.users', 'Användare', default=lambda self: self.env.user)
    name = fields.Char('Namn', required=True)
    contact_code = fields.Char('Kundnummer', required=True)
    contact_key = fields.Char('Kontakt', required=True, search=False)
    national_registration_number = fields.Char('Personnummer', required=True)
    phone_number = fields.Char('Telefonnummer')
    email_address = fields.Char('E-postadress')
    is_tenant = fields.Boolean('Är hyresgäst', default=True)

class OnecoreMaintenanceTenant(models.Model):
    _name = 'maintenance.tenant'
    _description = 'Tenant'

    name = fields.Char('Namn', required=True)
    contact_code = fields.Char('Kundnummer', required=True)
    contact_key = fields.Char('Kontakt', required=True, search=False)
    national_registration_number = fields.Char('Personnummer', required=True)
    phone_number = fields.Char('Telefonnummer')
    email_address = fields.Char('E-postadress')
    is_tenant = fields.Boolean('Är hyresgäst', default=True)
