from odoo import models, fields

class OnecoreMaintenanceRentalPropertyOption(models.Model):
    _name = 'maintenance.rental.property.option'
    _description = 'Rental Property Option'

    user_id = fields.Many2one('res.users', 'User', default=lambda self: self.env.user)
    name = fields.Char('name', required=True)
    property_type = fields.Char('Property Type', required=True)
    address = fields.Char('Address')
    code = fields.Char('Code')
    type = fields.Char('Type')
    area = fields.Char('Size')
    entrance = fields.Char('Entrance')
    floor = fields.Char('Floor')
    has_elevator = fields.Char('Has Elevator')
    wash_space = fields.Char('Wash Space')
    estate_code = fields.Char('Estate Code')
    estate = fields.Char('Estate Name')
    building_code = fields.Char('Block Code')
    building = fields.Char('Block Name')
    lease_ids = fields.One2many('maintenance.lease.option', 'rental_property_option_id', string='Leases')
    maintenance_unit_ids = fields.One2many('maintenance.maintenance.unit.option', 'rental_property_option_id', string='Maintenance Units Options')


class OnecoreMaintenanceRentalProperty(models.Model):
    _name = 'maintenance.rental.property'
    _description = 'Rental Property'

    rental_property_id = fields.Char(string='Rental Property ID', store=True)
    name = fields.Char('name', required=True)
    property_type = fields.Char('Property Type', required=True)
    address = fields.Char('Address')
    code = fields.Char('Code')
    type = fields.Char('Type')
    area = fields.Char('Size')
    entrance = fields.Char('Entrance')
    floor = fields.Char('Floor')
    has_elevator = fields.Char('Has Elevator')
    wash_space = fields.Char('Wash Space')
    estate_code = fields.Char('Estate Code')
    estate = fields.Char('Estate Name')
    building_code = fields.Char('Block Code')
    building = fields.Char('Block Name')

