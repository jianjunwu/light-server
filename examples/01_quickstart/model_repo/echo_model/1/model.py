from light_server import LitAPI


class EchoAPI(LitAPI):
    """最简模型示例：输入什么，返回什么。"""

    def setup(self, device):
        self.model = lambda x: x

    def decode_request(self, request, **kwargs):
        return request.get("input", "")

    def predict(self, x, **kwargs):
        return self.model(x)

    def encode_response(self, output, **kwargs):
        return {"output": output}
