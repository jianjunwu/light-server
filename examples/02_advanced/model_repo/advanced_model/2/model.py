import light_server as ls
from prometheus_client import Counter, Histogram


class AdvancedAPI(ls.LitAPI):
    """进阶模型 v2：将 multiplier 改为加法，演示版本切换。"""

    request_counter = Counter(
        "advanced_model_requests_total",
        "Total requests processed",
    )
    predict_latency = Histogram(
        "advanced_model_predict_seconds",
        "Predict latency distribution",
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    )

    def setup(self, device):
        self.addend = self.config.get("addend", 100)
        self.logger.info(f"setup: addend={self.addend}")

    def decode_request(self, request, **kwargs):
        return request.get("input", 0)

    def predict(self, x, **kwargs):
        self.request_counter.inc()
        with self.predict_latency.time():
            if isinstance(x, list):
                return [val + self.addend for val in x]
            return x + self.addend

    def encode_response(self, output, **kwargs):
        return {"result": output}
