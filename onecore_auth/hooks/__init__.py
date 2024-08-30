import os
from dotenv import load_dotenv

def _post_init_hook(env):
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))
    _insert_env_variables(env)

def _insert_env_variables(env):
    env['ir.config_parameter'].set_param('onecore_username', os.getenv('onecore_username'))
    env['ir.config_parameter'].set_param('onecore_password', os.getenv('onecore_password'))
    env['ir.config_parameter'].set_param('onecore_base_url', os.getenv('onecore_base_url'))