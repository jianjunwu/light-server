from light_server import LitAPI


class PreprocessAPI(LitAPI):
    """预处理模型：对输入进行分词和归一化。"""

    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return request.get("text", "")

    def predict(self, text, **kwargs):
        # 简单的预处理：转小写、去除多余空格、分词
        cleaned = " ".join(text.lower().split())
        tokens = cleaned.split()
        return {"cleaned_text": cleaned, "tokens": tokens, "token_count": len(tokens)}

    def encode_response(self, output, **kwargs):
        return output
