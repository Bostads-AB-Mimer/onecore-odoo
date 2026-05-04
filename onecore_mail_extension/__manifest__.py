# -*- coding: utf-8 -*-

{
    "author": "Bostads-AB-Mimer",
    "name": "ONECore Mail Extension",
    "version": "19.0.1.0",
    "sequence": 100,
    "category": "Productivity/Discuss",
    "description": "Extends the mail module with ONECore features.",
    "depends": ["base", "mail"],
    "summary": "Extends the mail module with ONECore features.",
    "data": [
        "data/mail_subtypes.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "mail/static/src/**/primary_variables.scss",
        ],
        "web.assets_backend": [
            "onecore_mail_extension/static/src/tenant/**/*",
        ],
    },
    "website": "https://www.odoo.com/app/discuss",
    "auto_install": True,
    "license": "LGPL-3",
}
