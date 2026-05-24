"""Double model: computes x * 2."""

import light_server as ls


class DoubleAPI(ls.LitAPI):
    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return float(request["x"])

    def predict(self, x, **kwargs):
        return x * 2

    def encode_response(self, output, **kwargs):
        return {"result": output}
