from odoo import _

from odoo.addons.helpdesk_mgmt.controllers.myaccount import CustomerPortalHelpdesk


class OnecoreCustomerPortalHelpdesk(CustomerPortalHelpdesk):
    """Swedish labels for the sort, group and search options on /my/tickets
    where helpdesk_mgmt's Swedish translation is wrong."""

    def _ticket_get_searchbar_sortings(self):
        sortings = super()._ticket_get_searchbar_sortings()
        sortings["stage"]["label"] = _("Status")
        sortings["update"]["label"] = _("Senaste statusändring")
        return sortings

    def _ticket_get_searchbar_groupby(self):
        groupby = super()._ticket_get_searchbar_groupby()
        groupby["stage"]["label"] = _("Status")
        return groupby

    def _ticket_get_searchbar_inputs(self):
        inputs = super()._ticket_get_searchbar_inputs()
        inputs["all"]["label"] = _("Sök i alla")
        return inputs
