"""Client-side pipeline for the CV example.

Usage:
    1. Start the server first:
       cd examples/03_cv_pipeline && light-server serve --config server.yaml

    2. Run this script:
       python client.py [path/to/image.jpg]

If no image path is provided, a synthetic test image is used.
"""

import base64
import io
import sys
from pathlib import Path

import requests
from PIL import Image

BASE_URL = "http://127.0.0.1:8000"


def load_image(path: str | None = None) -> Image.Image:
    if path and Path(path).exists():
        return Image.open(path).convert("RGB")
    # Generate a synthetic test image
    img = Image.new("RGB", (224, 224), color=(128, 64, 192))
    return img


def classify_image(image: Image.Image) -> dict:
    """Run the full preprocess -> predict pipeline."""
    # Encode image to base64
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    # Step 1: preprocess
    r1 = requests.post(
        f"{BASE_URL}/v2/models/preprocess/infer",
        json={"image_base64": img_b64},
    )
    r1.raise_for_status()
    tensor = r1.json()["tensor"]

    # Step 2: predict
    r2 = requests.post(
        f"{BASE_URL}/v2/models/predict/infer",
        json={"tensor": tensor},
    )
    r2.raise_for_status()
    return r2.json()


def main():
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    image = load_image(image_path)
    source = image_path if image_path else "synthetic test image"

    print("=" * 60)
    print("Image Classification Pipeline Demo")
    print(f"Source: {source}")
    print("=" * 60)

    result = classify_image(image)
    print("\nTop-5 predictions:")
    for i, pred in enumerate(result["top5"], 1):
        print(
            f"  {i}. {pred['class_name']} "
            f"(confidence: {pred['confidence']}, id: {pred['class_id']})"
        )


if __name__ == "__main__":
    main()
