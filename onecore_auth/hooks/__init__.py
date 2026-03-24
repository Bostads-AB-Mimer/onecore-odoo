def _post_init_hook(env):
    """Setup Keycloak configuration after module installation."""
    _setup_keycloak_auth(env)


def _setup_keycloak_auth(env):
    """Configure Keycloak authentication settings following OpenID Connect pattern."""
    oauth_provider = env["auth.oauth.provider"].search(
        [("name", "=", "Login with Keycloak")]
    )

    if not oauth_provider:
        oauth_provider = env["auth.oauth.provider"].create(
            {
                "name": "Login with Keycloak",
                "client_id": "odoo",
                "auth_endpoint": "https://auth.dev.mimer.nu/realms/master/protocol/openid-connect/auth",
                "scope": "openid",
                "validation_endpoint": "https://auth.dev.mimer.nu/realms/master/protocol/openid-connect/token",
                "data_endpoint": "https://auth.dev.mimer.nu/realms/master/protocol/openid-connect/userinfo",
                "enabled": True,
                "css_class": "fa fa-key",
                "body": "Login with Keycloak",
            }
        )
    config = env["ir.config_parameter"].sudo()
    config.set_param("auth_oauth.allow_oauth", True)

    print(f"Keycloak OAuth provider configured: {oauth_provider.name}")
