import os
from dotenv import dotenv_values

def _post_init_hook(env):
    config = dotenv_values(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
    _insert_env_variables(env, config)

def _insert_env_variables(env, config):
    for key, value in config.items():
        env['ir.config_parameter'].set_param(key, value)