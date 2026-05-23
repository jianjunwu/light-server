"""Text sentiment classification using a pre-trained DistilBERT model.

This example demonstrates non-streaming NLP inference with a real
transformers model. The model is automatically downloaded on first run.

Requirements:
    pip install transformers torch

To use the rule-based fallback (no dependencies), the code will automatically
fall back if transformers is not installed.
"""

import logging

import light_server as ls

logger = logging.getLogger(__name__)


class SentimentAPI(ls.LitAPI):
    """Sentiment analysis API using DistilBERT fine-tuned on SST-2.

    Supports batch inference via the transformers pipeline.
    """

    def setup(self, device):
        self.device = device

        try:
            from transformers import pipeline

            model_name = "distilbert-base-uncased-finetuned-sst-2-english"
            device_id = 0 if device != "cpu" else -1
            self.classifier = pipeline(
                "sentiment-analysis",
                model=model_name,
                device=device_id,
            )
            self.using_transformers = True
            logger.info(f"Loaded {model_name} on {device}")
        except ImportError:
            logger.warning(
                "transformers not installed, using rule-based fallback. "
                "Install with: pip install transformers torch"
            )
            self.using_transformers = False

    def decode_request(self, request, **kwargs):
        return request.get("text", "")

    def predict(self, x, **kwargs):
        """Run sentiment classification on a batch of texts.

        Args:
            x: List of text strings (batched by LitServe).

        Returns:
            List of dicts, each with "label" and "score" keys.
        """
        if self.using_transformers:
            return self.classifier(x)
        return [self._rule_classify(t) for t in x]

    def _rule_classify(self, text: str) -> dict:
        """Simple keyword-based fallback when transformers is unavailable."""
        positive = ["good", "great", "excellent", "love", "happy", "amazing", "best", "awesome"]
        negative = ["bad", "terrible", "awful", "hate", "sad", "worst", "poor", "horrible"]
        text_lower = text.lower()
        pos_count = sum(1 for w in positive if w in text_lower)
        neg_count = sum(1 for w in negative if w in text_lower)
        if pos_count > neg_count:
            return {"label": "POSITIVE", "score": round(min(0.5 + pos_count * 0.08, 0.99), 4)}
        elif neg_count > pos_count:
            return {"label": "NEGATIVE", "score": round(min(0.5 + neg_count * 0.08, 0.99), 4)}
        return {"label": "NEUTRAL", "score": 0.5}

    def encode_response(self, output, **kwargs):
        return output
