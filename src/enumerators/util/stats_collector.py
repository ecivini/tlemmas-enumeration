import time
from contextlib import contextmanager


class StatsCollector:
    def __init__(self, computation_logger: dict[str, object] | None = None):
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
                prev = self._computation_logger[key]
                assert isinstance(prev, float)
                self._computation_logger[key] = prev + (time.perf_counter_ns() - start) / 1e9

    def log(self, key: str, value: object) -> None:
        if self._computation_logger is not None:
            self._computation_logger[key] = value
