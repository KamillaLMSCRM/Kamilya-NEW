"""Compatibility import for enrollment model users.

The canonical model lives in ``app.models.enrollment``.  Keeping this module
prevents older feature routers from failing at request time while imports are
gradually consolidated.
"""

from app.models.enrollment import Enrollment

__all__ = ["Enrollment"]
