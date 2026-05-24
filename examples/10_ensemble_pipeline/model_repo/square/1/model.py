"""Square model: computes x * x."""

import light_server as ls


class SquareAPI(ls.LitAPI):
    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return float(request["x"])

    def predict(self, x, **kwargs):
        return x * x

    def encode_response(self, output, **kwargs):
        return {"result": output}
