from odoo import api, fields, models

class MaintenanceTeam(models.Model):
    _inherit = 'maintenance.team'
    
    first_column_request_count = fields.Integer(
        compute='_compute_first_column_request_count',
        string="First Column Requests"
    )
    # OneCore cost center (= distrikt) this team is responsible for, e.g.
    # "61140" for Distrikt Väst. "Tilldela resursgrupp" on a request pairs
    # request.cost_center_code with this field — never with the (translatable,
    # renameable) team name. Seeded from data/maintenance.team.csv.
    cost_center_code = fields.Char(
        string="Kostnadsställe (distrikt)",
        index=True,
        help="Kod för kostnadsstället/distriktet i OneCore, t.ex. 61140 för "
        "Distrikt Väst. Används av knappen 'Tilldela resursgrupp' på ärenden.",
    )

    @api.depends('todo_request_ids')
    def _compute_first_column_request_count(self):
        """Compute the count of requests in the first column for each team"""
        stages = self.env['maintenance.stage'].search([], order='sequence')
        first_stage = stages[0] if stages else False
        
        for team in self:
            if first_stage:
                team.first_column_request_count = self.env['maintenance.request'].search_count([
                    ('maintenance_team_id', '=', team.id),
                    ('stage_id', '=', first_stage.id)
                ])
            else:
                team.first_column_request_count = 0