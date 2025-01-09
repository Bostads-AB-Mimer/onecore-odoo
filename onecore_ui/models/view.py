from odoo import fields, models

class View(models.Model):
    """
        Extends the base 'ir.ui.view' model to include a new type of view
        called 'mobile'.
    """
    _inherit = 'ir.ui.view'
    
    type = fields.Selection(selection_add=[('mobile', "Mobile")])
    
    def _is_qweb_based_view(self, view_type):
        return view_type == "mobile" or super()._is_qweb_based_view(view_type)

    def _get_view_info(self):
        return {'mobile': {'icon': 'fa fa-mobile'}} | super()._get_view_info()

class IrActionsActWindowView(models.Model):
    """
       Extends the base 'ir.actions.act_window.view' model to include
       a new view mode called 'mobile'.
   """
    _inherit = 'ir.actions.act_window.view'
    view_mode = fields.Selection(selection_add=[('mobile', "Mobile")], ondelete={'mobile': 'cascade'})