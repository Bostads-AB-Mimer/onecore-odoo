from odoo import models, fields

class OnecoreMaintenanceMaintenanceUnitOption(models.Model):
    _name = 'maintenance.maintenance.unit.option'
    _description = 'Maintenance Unit Option'

    name = fields.Char('name', required=True)
    type = fields.Char('Type', required=True)
    code = fields.Char('Code', required=True)
    caption = fields.Char('Caption', required=True)
    estate_code = fields.Char('Estate Code', required=True)
    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    rental_property_option_id = fields.Many2one('maintenance.rental.property.option', string='Rental Property Option')
    
    
class OnecoreMaintenanceMaintenanceUnit(models.Model):
    _name = 'maintenance.maintenance.unit'
    _description = 'Maintenance Unit'

    name = fields.Char('name', required=True)
    type = fields.Char('Type', required=True)
    caption = fields.Char('Caption', required=True)
    code = fields.Char('Code', required=True)
    estate_code = fields.Char('Estate Code', required=True)
