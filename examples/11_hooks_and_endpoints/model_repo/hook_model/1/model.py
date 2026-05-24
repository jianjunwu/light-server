"""Model with lifecycle hooks: on_request, on_response, health_check."""

import time
import light_server as ls


class HookModelAPI(ls.LitAPI):
    """
    A demo model that shows all three lifecycle hooks.

    - on_request  : inject auth info / validate input before inference
    - on_response : attach latency / request metadata to the output
    - health_check: custom model-level readiness probe
    """

    def setup(self, device):
        self.device = device
        self.request_count = 0

    def decode_request(self, request, **kwargs):
        return request.get("input", 0)

    def predict(self, x, **kwargs):
        return {"result": x * 2}

    def encode_response(self, output, **kwargs):
        return output

    # ------------------------------------------------------------------
    # Hook: called in the main process BEFORE the request is queued
    # ------------------------------------------------------------------
    def on_request(self, payload, request_meta):
        """Inject authentication info and log the request."""
        headers = request_meta.get("headers", {})
        auth = headers.get("authorization", "anonymous")

        # You can modify the payload here
        payload["_auth"] = auth
        payload["_received_at"] = time.time()
        return payload

    # ------------------------------------------------------------------
    # Hook: called in the main process AFTER the worker returns
    # ------------------------------------------------------------------
    def on_response(self, response, response_meta):
        """Attach latency and request metadata to the response."""
        request_meta = response_meta.get("request_meta", {})
        received_at = request_meta.get("received_at", 0)
        latency_ms = round((time.time() - received_at) * 1000, 2) if received_at else None

        response["_meta"] = {
            "model_name": response_meta.get("model_name"),
            "version": response_meta.get("version"),
            "status": response_meta.get("status"),
            "latency_ms": latency_ms,
        }
        return response

    # ------------------------------------------------------------------
    # Hook: called by GET /v2/models/{name}/ready
    # ------------------------------------------------------------------
    def health_check(self):
        """Return custom model-level health status."""
        return {
            "status": "healthy",
            "device": str(self.device),
            "uptime_requests": self.request_count,
        }
