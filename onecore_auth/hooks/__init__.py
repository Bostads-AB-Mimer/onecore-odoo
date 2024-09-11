import os
from dotenv import dotenv_values

def _post_init_hook(env):
    _insert_env_variables(env)

def _insert_env_variables(env):
    config = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
    if not config:
        config = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env.template'))
    for key, value in config.items():
        env['ir.config_parameter'].set_param(key, value)