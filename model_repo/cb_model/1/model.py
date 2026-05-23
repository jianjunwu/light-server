import light_server as ls


class CBModel(ls.LitAPI):
    """Continuous batching test model: generates tokens one at a time."""

    def setup(self, device):
        self.eos_token = "<EOS>"
        self.max_gen_len = 5
        self._active = {}

    def decode_request(self, request, **kwargs):
        return request.get("prompt", "")

    def has_active_requests(self):
        return len(self._active) > 0

    def has_capacity(self):
        return len(self._active) < self.max_batch_size

    def predict(self, inputs, generated_sequences):
        """Generate one token for each active sequence."""
        tokens = []
        for i, _prompt in enumerate(inputs):
            seq_len = len(generated_sequences[i])
            if seq_len >= self.max_gen_len:
                tokens.append(self.eos_token)
            else:
                tokens.append(f"tok_{seq_len}")
        return tokens

    def has_finished(self, uid, token, max_sequence_length):
        return token == self.eos_token

    def encode_response(self, token, **kwargs):
        return {"token": token}
