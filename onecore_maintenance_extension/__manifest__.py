# -*- coding: utf-8 -*-

{
    "name": "ONECore Maintenance Extension",
    "version": "1.0",
    "sequence": 100,
    "category": "Manufacturing/Maintenance",
    "description": "Extends the maintenance module with ONECore features.",
    "depends": ["maintenance", "onecore_auth", "onecore_ui"],
    "summary": "Extends the maintenance module with ONECore features.",
    "website": "https://www.odoo.com/app/maintenance",
    "data": [
        "security/maintenance.xml",
        "security/ir.model.access.csv",
        "views/maintenance_views.xml",
        "views/maintenance_team_view.xml",
        "views/mobile_view.xml",
        # Load initial Data
        "data/maintenance.team.csv",
        "data/maintenance.request.category.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "onecore_maintenance_extension/static/src/js/*.js",
            "onecore_maintenance_extension/static/src/views/*.xml",
            "onecore_maintenance_extension/static/src/scss/*.scss",
        ],
    },
    "post_init_hook": "_post_init_hook",
    "auto_install": True,
    "license": "LGPL-3",
}
