import queue
import threading

from .bridge.challenge import ChallengeStore
from .transfer.state import TransferStateStore


STATE = TransferStateStore()
CHALLENGES = ChallengeStore(ttl=60)
IMPORT_QUEUE = queue.Queue()
SERVER = None
CONFIG = None
BRIDGE_ERROR = None
WORKERS = set()
WORKERS_LOCK = threading.Lock()


def track_worker(worker):
    with WORKERS_LOCK:
        WORKERS.add(worker)


def untrack_worker(worker):
    with WORKERS_LOCK:
        WORKERS.discard(worker)


def wait_workers(timeout=2.0):
    with WORKERS_LOCK:
        workers = list(WORKERS)
    for worker in workers:
        worker.join(timeout=max(0.0, timeout / max(1, len(workers))))


def reset():
    global STATE, CHALLENGES, IMPORT_QUEUE, SERVER, CONFIG, BRIDGE_ERROR, WORKERS
    STATE = TransferStateStore()
    CHALLENGES = ChallengeStore(ttl=60)
    IMPORT_QUEUE = queue.Queue()
    SERVER = None
    CONFIG = None
    BRIDGE_ERROR = None
    with WORKERS_LOCK:
        WORKERS = {worker for worker in WORKERS if worker.is_alive()}
