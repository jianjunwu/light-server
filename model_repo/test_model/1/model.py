import light_server as ls
import utils

from prometheus_client import Counter, Histogram


class TestModel(ls.LitAPI):
    """Example model with custom Prometheus metrics."""

    # Business-level metrics: free naming, auto-aggregated via multiproc
    input_tokens = Counter(
        "test_model_input_tokens_total",
        "Total input tokens processed",
    )
    predict_latency = Histogram(
        "test_model_predict_seconds",
        "Predict latency distribution",
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
    )

    def setup(self, device):
        self.custom_label = self.config.get("custom_label", "default")
        self.logger.info(
            f"setup: custom_label={self.custom_label}"
        )

    def decode_request(self, request, **kwargs):
        return request["input"]

    def predict(self, x, **kwargs):
        self.input_tokens.inc(len(str(x).split()))
        with self.predict_latency.time():
            self.logger.info(f"predict called with input={x}")
            return utils.transform(x)

    def encode_response(self, output, **kwargs):
        return {"output": output}
