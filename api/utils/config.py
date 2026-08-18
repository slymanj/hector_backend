"""
Legacy JWT config shim — prefer api.utils.settings.

Never use hardcoded secrets. Values must come from environment.
"""
from api.utils.settings import settings

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
