# -*- coding: utf-8 -*-

{
    "name": "ONECore Mail Extension",
    "version": "1.1",
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
