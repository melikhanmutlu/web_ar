"""Per-model edit lock.

Save / Apply / Slice / Restore each read-modify-write the same model.glb.
Two of them running at once (double click, two tabs, several gunicorn workers)
lose one edit or collide on temp files. This serializes them with an advisory
file lock in the model's directory, so it works across processes -- the same
approach as upload._session_lock. fcntl is POSIX-only (production runs on
Linux); without it the lock is a no-op rather than failing the edit.
"""

import os
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

LOCK_FILENAME = ".edit.lock"
DEFAULT_TIMEOUT_SECONDS = 60.0


class ModelBusyError(Exception):
    """Another edit holds the model's lock and did not finish in time."""


class ModelEditLock:
    def __init__(self, model_dir, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.model_dir = model_dir
        self.timeout = timeout
        self._file = None

    def acquire(self):
        if fcntl is None:
            return self
        os.makedirs(self.model_dir, exist_ok=True)
        lock_file = open(os.path.join(self.model_dir, LOCK_FILENAME), "a")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    lock_file.close()
                    raise ModelBusyError("model is being edited")
                time.sleep(0.05)
        self._file = lock_file
        return self

    def release(self):
        if self._file is not None:
            try:
                fcntl.flock(self._file, fcntl.LOCK_UN)
            finally:
                self._file.close()
                self._file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
