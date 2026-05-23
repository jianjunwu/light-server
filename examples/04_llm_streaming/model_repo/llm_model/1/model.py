"""LLM streaming model — generates text token by token via WebSocket.

This example demonstrates streaming inference where the model yields
output tokens incrementally. The client receives each token as it is
generated, creating a real-time "typing" effect.

To use a real transformer model, uncomment the transformers block below
and install: pip install transformers torch
"""

import logging
import random

import light_server as ls

logger = logging.getLogger(__name__)


class LLMAPI(ls.LitAPI):
    """Mock LLM that streams generated tokens.

    predict() returns a generator that yields one token at a time.
    encode_response() passes each token through unchanged.
    """

    def setup(self, device):
        self.device = device
        # Vocabulary of tokens to simulate generation
        self.vocab = [
            "The", "quick", "brown", "fox", "jumps", "over", "the",
            "lazy", "dog.", "In", "a", "world", "of", "endless",
            "possibilities,", "every", "choice", "matters.", "Light",
            "Server", "provides", "fast", "and", "flexible", "inference",
            "for", "any", "Python", "model.", "\n",
        ]
        logger.info(f"LLM model loaded on {device}")

    def decode_request(self, request, **kwargs):
        prompt = request.get("prompt", "")
        max_tokens = request.get("max_tokens", 20)
        temperature = request.get("temperature", 0.7)
        return {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

    def predict(self, x, **kwargs):
        """Yield tokens one by one to simulate streaming generation."""
        max_tokens = x["max_tokens"]
        # Echo the prompt back as the first "token" for context
        if x["prompt"]:
            yield {"token": x["prompt"].strip() + " ", "type": "prompt_echo"}

        for i in range(max_tokens):
            token = random.choice(self.vocab)
            yield {"token": token + " ", "index": i}

    def encode_response(self, output, **kwargs):
        return output


# ============== REAL TRANSFORMERS VERSION (uncomment to use) ==============
#
# from transformers import AutoModelForCausalLM, AutoTokenizer
# import torch
#
# class LLMAPI(ls.LitAPI):
#     def setup(self, device):
#         self.device = device if device != "cpu" else "cpu"
#         model_name = "gpt2"  # or "distilgpt2" for smaller download
#         self.tokenizer = AutoTokenizer.from_pretrained(model_name)
#         self.model = AutoModelForCausalLM.from_pretrained(model_name)
#         self.model.to(self.device)
#         self.model.eval()
#         if self.tokenizer.pad_token is None:
#             self.tokenizer.pad_token = self.tokenizer.eos_token
#
#     def decode_request(self, request, **kwargs):
#         return {
#             "prompt": request.get("prompt", ""),
#             "max_tokens": request.get("max_tokens", 20),
#         }
#
#     def predict(self, x, **kwargs):
#         inputs = self.tokenizer(x["prompt"], return_tensors="pt").to(self.device)
#         generated = inputs["input_ids"]
#         for i in range(x["max_tokens"]):
#             with torch.no_grad():
#                 outputs = self.model(generated)
#                 next_token = torch.argmax(outputs.logits[:, -1, :], dim=-1, keepdim=True)
#                 generated = torch.cat([generated, next_token], dim=-1)
#                 token_text = self.tokenizer.decode(next_token[0], skip_special_tokens=True)
#                 yield {"token": token_text, "index": i}
#             if next_token[0][0] == self.tokenizer.eos_token_id:
#                 break
#
#     def encode_response(self, output, **kwargs):
#         return output
