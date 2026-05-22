import light_server as ls
from prometheus_client import Counter, Histogram


class AdvancedAPI(ls.LitAPI):
    """进阶模型：演示批处理 + 自定义 Prometheus 指标 + 配置读取。"""

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
        # 从 config.yaml 读取自定义配置
        self.multiplier = self.config.get("multiplier", 2)
        self.logger.info(f"setup: multiplier={self.multiplier}")

    def decode_request(self, request, **kwargs):
        return request.get("input", 0)

    def predict(self, x, **kwargs):
        self.request_counter.inc()
        with self.predict_latency.time():
            if isinstance(x, list):
                # 批处理路径
                return [val * self.multiplier for val in x]
            return x * self.multiplier

    def encode_response(self, output, **kwargs):
        return {"result": output}
