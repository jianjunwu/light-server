# 03_cv_pipeline — 图像分类流水线

演示 light-server 中真实 CV 场景的多模型流水线：图像预处理（resize + normalize）→ ResNet 分类推理。

## 目录结构

```
model_repo/
  preprocess/          # 图像预处理模型
    1/
      model.py         # PIL resize + ImageNet normalize
      config.yaml
  predict/             # 图像分类模型
    1/
      model.py         # ResNet-18 / TinyCNN fallback
      config.yaml      # 开启 batching
server.yaml            # 服务端配置
client.py              # Python 客户端：读取图片 → 流水线推理
run.sh                 # 一键运行
test_model.py          # 模型逻辑验证
```

## 依赖

```bash
pip install torch torchvision pillow
```

如果 torchvision 不可用，predict 模型会自动回退到 TinyCNN（纯 PyTorch 实现，无需下载权重）。

## 启动服务

```bash
cd examples/03_cv_pipeline
light-server serve --config server.yaml
```

服务启动后会同时加载 `preprocess` 和 `predict` 两个模型。

## 运行客户端

```bash
# 使用随机生成的测试图片
python client.py

# 或者指定本地图片
python client.py /path/to/your/image.jpg
```

## 分步调用

### 1. 预处理

```bash
curl -X POST http://127.0.0.1:8000/v2/models/preprocess/infer \
  -H "Content-Type: application/json" \
  -d '{"image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="}'
```

预期输出：

```json
{
  "tensor": [[[...]], [[...]], [[...]]],
  "shape": [3, 224, 224]
}
```

### 2. 推理

```bash
curl -X POST http://127.0.0.1:8000/v2/models/predict/infer \
  -H "Content-Type: application/json" \
  -d '{
    "tensor": [[[...]], [[...]], [[...]]]
  }'
```

预期输出（使用 TinyCNN fallback 时）：

```json
{
  "top5": [
    {"class_id": 3, "class_name": "class_3", "confidence": 0.1234},
    ...
  ]
}
```

使用 torchvision ResNet-18 时，`class_name` 为 ImageNet 类别名称（如 "golden retriever"）。

## 客户端流水线脚本

实际场景中，可以在客户端将两个步骤封装为一次调用：

```python
from PIL import Image
import requests

def classify_image(image_path):
    img = Image.open(image_path).convert("RGB")
    # Encode to base64
    import base64, io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    # Step 1: preprocess
    r1 = requests.post(
        "http://127.0.0.1:8000/v2/models/preprocess/infer",
        json={"image_base64": img_b64},
    )
    tensor = r1.json()["tensor"]

    # Step 2: predict
    r2 = requests.post(
        "http://127.0.0.1:8000/v2/models/predict/infer",
        json={"tensor": tensor},
    )
    return r2.json()

print(classify_image("cat.jpg"))
# {'top5': [{'class_id': 281, 'class_name': 'tabby cat', 'confidence': 0.9123}, ...]}
```

## 管理 API

```bash
# 查看已加载模型
curl http://127.0.0.1:8000/v2/models

# 单独加载/卸载某个模型
curl -X POST http://127.0.0.1:8000/v2/repository/models/predict/load
curl -X POST http://127.0.0.1:8000/v2/repository/models/preprocess/unload

# 查看指标
curl http://127.0.0.1:8002/metrics
```

## 扩展思路

- **后端串联**：在 `predict/model.py` 的 `decode_request` 中直接调用 `preprocess` 模型，对客户端暴露单一端点
- **模型组合**：light-server 内置的 ensemble 模块支持定义模型间的 DAG 依赖关系
- **A/B 测试**：同时加载 `predict/1` 和 `predict/2`，通过管理 API 切换活跃版本
- **GPU 加速**：将 `accelerator` 改为 `cuda`，模型自动在 GPU 上运行
