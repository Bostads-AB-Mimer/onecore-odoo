from odoo import models, fields

class View(models.Model):
    """
        Extends the base 'ir.ui.view' model to include a new type of view
        called 'mobile'.
    """
    _inherit = 'ir.ui.view'
    type = fields.Selection(selection_add=[('mobile', "Mobile")])

class IrActionsActWindowView(models.Model):
    """
       Extends the base 'ir.actions.act_window.view' model to include
       a new view mode called 'mobile'.
   """
    _inherit = 'ir.actions.act_window.view'
    view_mode = fields.Selection(selection_add=[('mobile', "Mobile")],
                                 ondelete={'mobile': 'cascade'})