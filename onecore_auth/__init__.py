from .setup import Setup
Setup.install_required_packages()

from . import models
from .hooks import _post_init_hook