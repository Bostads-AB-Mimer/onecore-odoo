{
    "name": "OneCore Base Extension",
    "author": "Bostads-AB-Mimer",
    "license": "LGPL-3",
    "category": "ONECore",
    "summary": "Extends the Odoo base module with ONECore specific customizations.",
    "sequence": 100,
    "version": "19.0.1.0.0",
    "depends": ["base", "mail_bot", "mail"],
    "data": [
        "views/res_users_view.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "onecore_base_extension/static/src/xml/messaging_menu.xml",
        ],
    },
    "auto_install": True,
}
