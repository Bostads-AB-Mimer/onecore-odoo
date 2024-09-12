import os
from dotenv import dotenv_values

def _post_init_hook(env):
    _insert_env_variables(env)

def _insert_env_variables(env):
    # Load variables from .env.template
    env_template_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env.template')
    env_template_config = dotenv_values(env_template_path)

    # Check if all variables from .env.template are present in odoo-env secret
    all_in_secret = all(var in os.environ for var in env_template_config)

    if all_in_secret:
        for key in env_template_config:
            env['ir.config_parameter'].set_param(key, os.environ[key])
    else:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        env_config = dotenv_values(env_path)

        for key, value in env_template_config.items():
            if key in env_config:
                env['ir.config_parameter'].set_param(key, env_config[key])
            else:
                env['ir.config_parameter'].set_param(key, value)