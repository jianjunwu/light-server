import light_server as ls


class StreamModel(ls.LitAPI):
    """Bidirectional streaming test model: echoes each input chunk."""

    def setup(self, device):
        pass

    def decode_request(self, request, **kwargs):
        return request

    def predict(self, x, **kwargs):
        return x

    def stream_predict(self, input_gen, **kwargs):
        """Receive chunks and yield echo responses."""
        for chunk in input_gen:
            yield {"echo": chunk}

    def encode_response(self, output, **kwargs):
        return output
