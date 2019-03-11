VERSION = (0, 9, 4)

try:
    from .decorators import job
    from .queues import enqueue, get_connection, get_queue, get_scheduler, get_failed_queue
    from .workers import get_worker
except ImportError:
    pass
