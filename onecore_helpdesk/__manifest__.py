{
    "author": "Bostads-AB-Mimer",
    "name": "ONECore Helpdesk",
    "version": "19.0.1.0.0",
    "sequence": 100,
    "category": "ONECore",
    "summary": "IT tickets on top of OCA helpdesk_mgmt",
    "description": "Mimer-specific configuration for IT tickets (teams, stages, "
    "categories, automations), built on the vendored OCA helpdesk modules. "
    "Separate from the property work orders in onecore_maintenance_extension.",
    "depends": [
        "base_automation",
        "helpdesk_mgmt",
        "helpdesk_ticket_partner_response",
        "helpdesk_ticket_close_inactive",
    ],
    "data": [
        "data/helpdesk_it_team_data.xml",
        "data/helpdesk_p1_alarm_data.xml",
    ],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
