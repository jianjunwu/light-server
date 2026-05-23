"""Compute model with simulated latency to demonstrate batching speedup."""

import time

import light_server as ls


class ComputeAPI(ls.LitAPI):
    """
    A model that simulates fixed compute latency per batch.
    With batching, multiple requests are processed together,
    dramatically improving throughput.
    """

    COMPUTE_TIME = 0.05  # 50ms per batch

    def setup(self, device):
        self.device = device

    def decode_request(self, request, **kwargs):
        return request.get("number", 0)

    def predict(self, numbers, **kwargs):
        # Simulate fixed compute cost per batch
        time.sleep(self.COMPUTE_TIME)
        if not isinstance(numbers, list):
            numbers = [numbers]
        batch_size = len(numbers)
        return [
            {"result": n * n, "batch_size": batch_size}
            for n in numbers
        ]

    def encode_response(self, output, **kwargs):
        return output
