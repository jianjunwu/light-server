# 06_text_classification — 文本情感分类

演示 light-server 的真实 NLP 模型推理：使用 `transformers` 的预训练 DistilBERT 模型对文本进行情感分类（正面 / 负面 / 中性）。支持自适应批处理（adaptive batching），多条请求会自动合并为 batch 送入模型。

## 目录结构

```
model_repo/
  sentiment/1/
    model.py          # DistilBERT sentiment-analysis pipeline
    config.yaml       # max_batch_size: 8, batch_timeout: 0.01
server.yaml
client.py             # HTTP 客户端：单条 + 批量推理
test_model.py         # 不依赖 server，直接验证 model.py 逻辑
run.sh                # 一键运行（测试 + 启动服务 + 客户端）
```

## 🎯 30 秒体验

```bash
cd examples/06_text_classification
./run.sh
```

终端会自动完成：验证模型逻辑 → 启动服务 → 运行单条 + 批量推理客户端 → 停止服务。

## 📸 运行效果

```
🔧 Step 1/4: 验证模型逻辑...
✅ Model logic test passed!

🚀 Step 2/4: 启动 light-server...
⏳ Step 3/4: 等待服务就绪...

🧪 Step 4/4: 运行情感分析客户端...

========================================
📝 Single Inference
========================================
  Text:     I love this product!
  Result:   POSITIVE (score: 0.9998)

  Text:     This is terrible.
  Result:   NEGATIVE (score: 0.9987)

  Text:     The weather is okay.
  Result:   NEUTRAL (score: 0.5123)

========================================
🚀 Batch Inference (6 texts, auto-batched)
========================================
  Batch size seen: 6
  Results:
    1. POSITIVE  (0.9998)
    2. NEGATIVE  (0.9987)
    3. NEUTRAL   (0.5123)
    4. POSITIVE  (0.9876)
    5. NEGATIVE  (0.9654)
    6. POSITIVE  (0.9991)

========================================
✅ All tests passed!
```

## 环境准备

```bash
pip install transformers torch requests
```

首次运行时会自动从 Hugging Face 下载模型（约 250MB）：
`distilbert-base-uncased-finetuned-sst-2-english`

如果未安装 `transformers`，代码会自动回退到基于关键词规则的简单分类器，方便快速体验。

## 启动服务

```bash
cd examples/06_text_classification
light-server serve --config server.yaml
```

## 运行客户端

```bash
python client.py
```

客户端会执行两部分测试：
1. **单条推理**：发送 3 条文本，查看分类结果
2. **批量推理**：发送 6 条文本（高并发下 server 会自动 batch）

## 核心原理

### 模型端（model.py）

```python
class SentimentAPI(ls.LitAPI):
    def setup(self, device):
        # 加载 transformers pipeline
        self.classifier = pipeline(
            "sentiment-analysis",
            model="distilbert-base-uncased-finetuned-sst-2-english",
        )

    def decode_request(self, request):
        return request.get("text", "")

    def predict(self, x):
        # x 为 batch 后的文本列表，pipeline 原生支持 batch
        return self.classifier(x)

    def encode_response(self, output):
        return output  # {"label": "POSITIVE", "score": 0.99}
```

### 配置端（config.yaml）

```yaml
max_batch_size: 8      # 最大 batch 数
batch_timeout: 0.01    # 等待凑 batch 的超时时间（秒）
accelerator: cpu
```

当短时间内收到多条请求时，server 会在 `batch_timeout` 窗口内将请求合并为一个 batch 送入 `predict()`，显著提升吞吐。

### 请求格式

单条：
```bash
curl -X POST http://127.0.0.1:8000/v2/models/sentiment/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "I love this product!"}'
```

返回：
```json
{"label": "POSITIVE", "score": 0.9998}
```

## 扩展思路

- **切换模型**：修改 `setup()` 中的 `model_name`，可替换为其他 `transformers` 分类模型，如 `cardiffnlp/twitter-roberta-base-sentiment-latest`
- **多标签分类**：将 `pipeline("sentiment-analysis")` 改为 `pipeline("text-classification", model=...)`，支持多类别分类
- **接入自定义模型**：在 `setup()` 中加载本地 fine-tuned 的 PyTorch / TensorFlow 模型
- **GPU 加速**：将 `accelerator: cpu` 改为 `accelerator: gpu`，pipeline 会自动使用 CUDA
