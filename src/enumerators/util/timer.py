import time
from contextlib import contextmanager


class Timer:
    """Context manager for timing code blocks and storing results in a computation logger dict."""

    def __init__(self, computation_logger: dict | None = None):
        self._computation_logger = computation_logger

    @contextmanager
    def track_time(self, key: str):
        if self._computation_logger is None:
            yield
        else:
            if key not in self._computation_logger:
                self._computation_logger[key] = 0.0
            start = time.perf_counter_ns()
            try:
                yield
            finally:
                self._computation_logger[key] += (time.perf_counter_ns() - start) / 1e9
