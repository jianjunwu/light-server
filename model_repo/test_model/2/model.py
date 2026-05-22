import light_server as ls
import utils


class TestModel(ls.LitAPI):
    def setup(self, device):
        self.custom_label = self.config.get("custom_label", "default")
        self.logger.info(
            f"setup: custom_label={self.custom_label}"
        )

    def decode_request(self, request, **kwargs):
        return request["input"]

    def predict(self, x, **kwargs):
        self.logger.info(f"predict called with input={x}")
        return utils.transform(x)

    def encode_response(self, output, **kwargs):
        return {"output": output}

    def on_file_changed(self, changed_files):
        self.logger.info(
            f"on_file_changed called with "
            f"{len(changed_files)} files"
        )
        return "handled"
