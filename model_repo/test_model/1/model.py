import light_server as ls

class TestModel(ls.LitAPI):
    def setup(self, device):
        self.model = lambda x: x ** 2

    def decode_request(self, request):
        return request["input"]

    def predict(self, x):
        self.logger.info(f"predict called with input={x}")
        return self.model(x)

    def encode_response(self, output):
        return {"output": output}
