import os

from apps.core import env

from .base import *

DEBUG = env.get_bool("DEBUG", True)
SECRET_KEY = env.ensure_secret_key(SECRET_KEY)
LUMI_JOB_DISPATCH = os.environ.get("LUMI_JOB_DISPATCH", "eager")
