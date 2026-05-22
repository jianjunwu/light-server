from light_server import LitAPI


class PredictAPI(LitAPI):
    """推理模型：基于预处理结果做情感分析（简单规则演示）。"""

    def setup(self, device):
        self.positive_words = {"good", "great", "excellent", "happy", "love", "awesome"}
        self.negative_words = {"bad", "terrible", "sad", "hate", "awful", "worst"}

    def decode_request(self, request, **kwargs):
        return request.get("tokens", [])

    def predict(self, tokens, **kwargs):
        if not tokens:
            return {"sentiment": "neutral", "score": 0.0}

        pos_count = sum(1 for t in tokens if t in self.positive_words)
        neg_count = sum(1 for t in tokens if t in self.negative_words)
        total = len(tokens)

        score = (pos_count - neg_count) / total
        if score > 0.1:
            sentiment = "positive"
        elif score < -0.1:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return {
            "sentiment": sentiment,
            "score": round(score, 3),
            "positive_words": pos_count,
            "negative_words": neg_count,
        }

    def encode_response(self, output, **kwargs):
        return output
