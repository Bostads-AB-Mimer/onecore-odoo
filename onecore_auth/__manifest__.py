# -*- coding: utf-8 -*-
{
    "name": "ONECore Authentication",
    "version": "1.0",
    "sequence": 50,
    "category": "Authentication",
    "description": "Keycloak authentication integration for ONECore.",
    "depends": ["base", "web", "auth_oauth"],
    "data": [],
    "post_init_hook": "_post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
