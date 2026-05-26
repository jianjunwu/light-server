"""Sleep model: CPU-bound mock for benchmarking IPC overhead.

This model simulates fixed compute latency using time.sleep(),
ensuring that performance differences between light_server and LitServe
are due to their process/IPC architectures, not model inference time.
"""

import time

import light_server as ls


class SleepAPI(ls.LitAPI):
    """A model that sleeps for a fixed duration per request."""

    SLEEP_TIME = 0.01  # 10ms per request

    def setup(self, device):
        self.device = device

    def decode_request(self, request, **kwargs):
        return request.get("input", "")

    def predict(self, inputs, **kwargs):
        time.sleep(self.SLEEP_TIME)
        if isinstance(inputs, list):
            return [{"output": i, "sleep_ms": self.SLEEP_TIME * 1000} for i in inputs]
        return {"output": inputs, "sleep_ms": self.SLEEP_TIME * 1000}

    def encode_response(self, output, **kwargs):
        return output
