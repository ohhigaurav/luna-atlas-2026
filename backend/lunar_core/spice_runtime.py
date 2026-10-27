"""Process-wide synchronization for the CSPICE kernel pool and geometry calls."""

from threading import RLock

# CSPICE uses a process-global kernel pool. Loading/clearing kernels must not race with queries.
SPICE_LOCK = RLock()
