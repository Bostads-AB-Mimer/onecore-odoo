{
    "name": "ONECore UI",
    "version": "1.0",
    "sequence": 100,
    "category": "ONECore",
    "description": "Provides ONECore UI",
    "depends": ["web"],
    "summary": "Provides ONECore UI",
    "assets": {
        "web.assets_backend": [
            "onecore_ui/static/src/js/*.js",
            "onecore_ui/static/src/views/*.xml",
        ],
    },
    "auto_install": True,
    "license": "LGPL-3",
}
