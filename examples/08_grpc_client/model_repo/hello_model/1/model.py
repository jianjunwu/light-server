"""Hello World model: smart text enhancement with zero dependencies."""

import random

import light_server as ls


class HelloAPI(ls.LitAPI):
    """
    A fun "hello world" model that enhances user text with emoji and
    friendly responses based on detected sentiment.  Pure Python, no
    external dependencies required.
    """

    MOOD_MAP = {
        "positive": {
            "keywords": ["love", "great", "awesome", "good", "happy", "nice",
                         "amazing", "excellent", "wonderful", "perfect", "best",
                         "喜欢", "好", "棒", "优秀", "开心"],
            "emojis": ["❤️", "✨", "🎉", "🌟", "🚀", "💯"],
            "replies": [
                "That's fantastic!",
                "Absolutely amazing!",
                "So glad to hear that!",
                "太棒了！",
                "真为你高兴！",
            ],
        },
        "negative": {
            "keywords": ["bad", "sad", "hate", "terrible", "awful", "worst",
                         "讨厌", "差", "糟糕", "难过", "生气"],
            "emojis": ["😔", "💪", "🤗", "🌈", "💙"],
            "replies": [
                "Sorry to hear that...",
                "Things will get better!",
                "Sending positive vibes!",
                "别难过，会好起来的！",
                "加油！",
            ],
        },
        "question": {
            "keywords": ["what", "how", "why", "when", "where", "which",
                         "什么", "怎么", "为什么", "哪里", "如何"],
            "emojis": ["🤔", "💡", "🔍", "❓", "🧠"],
            "replies": [
                "Great question!",
                "Let me think...",
                "Interesting inquiry!",
                "好问题！",
                "让我想想...",
            ],
        },
        "greeting": {
            "keywords": ["hello", "hi", "hey", "morning", "afternoon",
                         "evening", "你好", "嗨", "早上好", "晚上好"],
            "emojis": ["👋", "😊", "🌞", "🌙", "✨"],
            "replies": [
                "Welcome to light-server!",
                "Great to see you!",
                "Ready to help!",
                "欢迎来到 light-server！",
                "很高兴见到你！",
            ],
        },
    }

    def setup(self, device):
        self.device = device

    def _detect_mood(self, text: str) -> str:
        text_lower = text.lower()
        scores = {}
        for mood, data in self.MOOD_MAP.items():
            score = sum(len(kw) for kw in data["keywords"] if kw in text_lower)
            scores[mood] = score
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "neutral"

    def decode_request(self, request, **kwargs):
        return request.get("text", "")

    def predict(self, text, **kwargs):
        mood = self._detect_mood(text)
        if mood == "neutral":
            return {
                "original": text,
                "enhanced": f"{text} ✨",
                "mood": "neutral",
            }

        data = self.MOOD_MAP[mood]
        emoji = random.choice(data["emojis"])
        reply = random.choice(data["replies"])
        enhanced = f"{text} {emoji} {reply}"

        return {
            "original": text,
            "enhanced": enhanced,
            "mood": mood,
        }

    def encode_response(self, output, **kwargs):
        return output
