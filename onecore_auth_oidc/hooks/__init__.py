def _post_init_hook(env):
    """Setup Keycloak OIDC configuration after module installation."""
    _setup_keycloak_oidc(env)


def _setup_keycloak_oidc(env):
    """Configure Keycloak OpenID Connect authentication settings."""
    import os

    oauth_provider = env["auth.oauth.provider"].search(
        [("name", "=", "Login with Keycloak")]
    )

    if not oauth_provider:
        client_secret = os.environ.get("KEYCLOAK_CLIENT_SECRET", "")

        oauth_provider = env["auth.oauth.provider"].create(
            {
                "name": "Logga in med Keycloak",
                "client_id": "odoo",
                "client_secret": client_secret,
                "flow": "id_token_code",  # OpenID Connect (authorization code flow)
                "auth_endpoint": "https://auth.dev.mimer.nu/realms/onecore/protocol/openid-connect/auth",
                "token_endpoint": "https://auth.dev.mimer.nu/realms/onecore/protocol/openid-connect/token",
                "jwks_uri": "https://auth.dev.mimer.nu/realms/onecore/protocol/openid-connect/certs",
                "scope": "openid email",
                "token_map": "sub:user_id",
                "enabled": True,
                "css_class": "fa fa-key",
                "body": "Login with Keycloak",
            }
        )

    config = env["ir.config_parameter"].sudo()
    config.set_param("auth_oauth.allow_oauth", True)

    print(f"Keycloak OIDC provider configured: {oauth_provider.name}")
