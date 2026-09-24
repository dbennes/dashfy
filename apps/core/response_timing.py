"""Public stage durations, without user data, SQL or connection details."""
from time import perf_counter


class ResponseTiming:
    def __init__(self):
        self.started = self.previous = perf_counter()
        self.stages = []

    def mark(self, name):
        now = perf_counter()
        self.stages.append((name, (now - self.previous) * 1000))
        self.previous = now

    def attach(self, response):
        durations = [*self.stages, ("total", (perf_counter() - self.started) * 1000)]
        response["Server-Timing"] = ", ".join(f"{name};dur={duration:.1f}" for name, duration in durations)
        return response
