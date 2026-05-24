"""Combine model: sums two inputs."""

import light_server as ls


class CombineAPI(ls.LitAPI):
    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return float(request["a"]), float(request["b"])

    def predict(self, inputs, **kwargs):
        a, b = inputs
        return a + b

    def encode_response(self, output, **kwargs):
        return {"result": output}
