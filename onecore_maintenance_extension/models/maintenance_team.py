from odoo import models, fields

class OnecoreMaintenanceTeam(models.Model):
    _inherit = 'maintenance.team'

    user_ids = fields.Many2many('res.users', string='Team Members')
