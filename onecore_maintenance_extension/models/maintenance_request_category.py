from odoo import models, fields

class OnecoreMaintenanceRequestCategory(models.Model):
    _name = 'maintenance.request.category'
    _description = 'Maintenance Request Category'

    name = fields.Char('Namn', required=True)
    active = fields.Boolean(default=True)
    color = fields.Integer("Färg", default=0)
