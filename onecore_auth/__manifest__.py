# -*- coding: utf-8 -*-
{
    "author": "Bostads-AB-Mimer",
    "name": "ONECore Authentication",
    "version": "1.2",
    "sequence": 50,
    "category": "Authentication",
    "description": "Keycloak authentication integration for ONECore.",
    "depends": ["base", "web", "auth_oauth"],
    "data": ["data/ir_config_parameter.xml"],
    "post_init_hook": "_post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
