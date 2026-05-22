from light_server import LitAPI


class SentimentAPI(LitAPI):
    """A simple rule-based sentiment classifier for demo purposes."""

    def setup(self, device):
        self.positive_words = {"great", "good", "excellent", "amazing", "love", "wonderful", "best", "happy", "nice"}
        self.negative_words = {"bad", "terrible", "awful", "hate", "worst", "sad", "poor", "disappointing"}

    def decode_request(self, request, **kwargs):
        return request.get("text", "")

    def predict(self, text, **kwargs):
        tokens = text.lower().split()
        pos = sum(1 for t in tokens if t in self.positive_words)
        neg = sum(1 for t in tokens if t in self.negative_words)
        total = pos + neg
        if total == 0:
            return {"sentiment": "neutral", "score": 0.0, "positive_words": pos, "negative_words": neg}
        score = (pos - neg) / len(tokens)
        sentiment = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return {"sentiment": sentiment, "score": round(score, 3), "positive_words": pos, "negative_words": neg}

    def encode_response(self, output, **kwargs):
        return output
