"""Image preprocessing model: resize, crop, normalize, and convert to tensor."""

import base64
import io
from pathlib import Path

import light_server as ls
from PIL import Image


class PreprocessAPI(ls.LitAPI):
    """Accept a base64-encoded image and return a normalized tensor."""

    def setup(self, device):
        self.device = device
        self.target_size = (224, 224)
        # ImageNet normalization
        self.mean = [0.485, 0.456, 0.406]
        self.std = [0.229, 0.224, 0.225]

    def decode_request(self, request, **kwargs):
        """Decode base64 image or use a test pattern."""
        img_b64 = request.get("image_base64")
        if img_b64:
            img_bytes = base64.b64decode(img_b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        else:
            # Generate a test pattern for quick validation
            img = Image.new("RGB", self.target_size, color=(128, 64, 192))
        return img

    def predict(self, img, **kwargs):
        """Resize, normalize, and convert to tensor."""
        img = img.resize(self.target_size)
        # Convert to tensor [H, W, C] then [C, H, W]
        arr = []
        for c in range(3):
            channel = []
            for y in range(self.target_size[1]):
                row = []
                for x in range(self.target_size[0]):
                    pixel = img.getpixel((x, y))[c] / 255.0
                    pixel = (pixel - self.mean[c]) / self.std[c]
                    row.append(round(pixel, 6))
                channel.append(row)
            arr.append(channel)
        return arr  # [3, 224, 224]

    def encode_response(self, output, **kwargs):
        return {"tensor": output, "shape": [3, 224, 224]}
