"""Image classification model using a pre-trained ResNet-18 from torchvision."""

import logging

import light_server as ls
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


# Tiny CNN for environments without torchvision (fallback)
class TinyCNN(nn.Module):
    def __init__(self, num_classes: int = 10):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 16, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.features(x)
        x = x.view(x.size(0), -1)
        return self.classifier(x)


class PredictAPI(ls.LitAPI):
    """Run image classification on a preprocessed tensor."""

    def setup(self, device):
        self.device = device if device != "cpu" else "cpu"

        try:
            import torchvision.models as models

            self.model = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
            weights = models.ResNet18_Weights.DEFAULT
            self.categories = weights.meta["categories"]
            self.num_classes = 1000
            logger.info("Loaded torchvision ResNet-18")
        except Exception:
            logger.warning("torchvision not available, using TinyCNN fallback")
            self.model = TinyCNN(num_classes=10)
            self.categories = [f"class_{i}" for i in range(10)]
            self.num_classes = 10

        self.model.eval()
        self.model.to(self.device)

    def decode_request(self, request, **kwargs):
        tensor_list = request["tensor"]
        # [3, H, W] -> [1, 3, H, W]
        tensor = torch.tensor(tensor_list, dtype=torch.float32).unsqueeze(0)
        return tensor.to(self.device)

    def predict(self, x, **kwargs):
        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1)
            top5 = torch.topk(probs, min(5, self.num_classes))
        return {
            "ids": top5.indices.squeeze(0).tolist(),
            "probs": top5.values.squeeze(0).tolist(),
        }

    def encode_response(self, output, **kwargs):
        top5 = [
            {
                "class_id": cid,
                "class_name": self.categories[cid],
                "confidence": round(p, 4),
            }
            for cid, p in zip(output["ids"], output["probs"])
        ]
        return {"top5": top5}
