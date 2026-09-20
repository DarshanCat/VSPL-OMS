from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared, in-memory rate limiter. In-memory is appropriate here since this application
# does not run multiple backend processes/instances behind a shared limiter store today
# (see docs/OMS_RELEASE_BASELINE.md) -- if that changes, back this with Redis instead.
limiter = Limiter(key_func=get_remote_address)
