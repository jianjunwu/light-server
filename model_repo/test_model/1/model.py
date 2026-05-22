import litserve as ls

class TestModel(ls.LitAPI):
    def setup(self, device):
        self.model = lambda x: x ** 2

    def decode_request(self, request):
        return request["input"]

    def predict(self, x):
        return self.model(x)

    def encode_response(self, output):
        return {"output": output}
