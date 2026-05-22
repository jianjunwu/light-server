# 03_ensemble — 多模型流水线

演示如何在 light-server 中部署多个模型，并通过客户端串联调用形成预处理 → 推理流水线。

## 目录结构

```
model_repo/
  preprocess/          # 预处理模型
    1/
      model.py
      config.yaml
  predict/             # 推理模型
    1/
      model.py
      config.yaml
```

## 启动服务

```bash
cd examples/03_ensemble
light-server serve --config server.yaml
```

服务启动后会同时加载 `preprocess` 和 `predict` 两个模型。

## 分步调用

### 1. 预处理

```bash
curl -X POST http://127.0.0.1:8000/v2/models/preprocess/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "This is a GREAT day and I love it"}'
```

预期输出：

```json
{
  "cleaned_text": "this is a great day and i love it",
  "tokens": ["this", "is", "a", "great", "day", "and", "i", "love", "it"],
  "token_count": 9
}
```

### 2. 推理

将预处理输出的 `tokens` 传给推理模型：

```bash
curl -X POST http://127.0.0.1:8000/v2/models/predict/infer \
  -H "Content-Type: application/json" \
  -d '{
    "tokens": ["this", "is", "a", "great", "day", "and", "i", "love", "it"]
  }'
```

预期输出：

```json
{
  "sentiment": "positive",
  "score": 0.222,
  "positive_words": 2,
  "negative_words": 0
}
```

## 客户端流水线脚本

实际场景中，可以在客户端将两个步骤封装为一次调用：

```python
import requests

def sentiment_analysis(text):
    # 步骤 1：预处理
    r1 = requests.post(
        "http://127.0.0.1:8000/v2/models/preprocess/infer",
        json={"text": text}
    )
    tokens = r1.json()["tokens"]

    # 步骤 2：推理
    r2 = requests.post(
        "http://127.0.0.1:8000/v2/models/predict/infer",
        json={"tokens": tokens}
    )
    return r2.json()

print(sentiment_analysis("I hate this terrible movie"))
# {'sentiment': 'negative', 'score': -0.286, 'positive_words': 0, 'negative_words': 2}
```

## 管理 API

```bash
# 查看已加载模型
curl http://127.0.0.1:8000/v2/models

# 单独加载/卸载某个模型
curl -X POST http://127.0.0.1:8000/v2/repository/models/predict/load
curl -X POST http://127.0.0.1:8000/v2/repository/models/preprocess/unload
```

## 扩展思路

- **后端串联**：在 `predict/model.py` 的 `decode_request` 中直接调用 `preprocess` 模型，对客户端暴露单一端点
- **模型组合**：light-server 内置的 ensemble 模块支持定义模型间的 DAG 依赖关系
- **A/B 测试**：同时加载 `predict/1` 和 `predict/2`，通过管理 API 切换活跃版本
