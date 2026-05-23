# 02_advanced — 进阶特性融合

演示批处理（batching）、自定义 Prometheus 指标、热重载（hot reload）和版本管理。

## 目录结构

```
model_repo/
  advanced_model/
    1/                 # v1：乘法运算
      model.py
      config.yaml
    2/                 # v2：加法运算
      model.py
      config.yaml
```

## 🎯 30 秒体验

```bash
cd examples/02_advanced
./run.sh
```

终端会自动完成：验证模型逻辑 → 启动服务 → 单条推理 → 批量推理 → 查看指标 → 版本切换 → 停止服务。

## 📸 运行效果

```
🔧 Step 1/4: 验证模型逻辑...
✅ Model logic test passed!

🚀 Step 2/4: 启动 light-server...
⏳ Step 3/4: 等待服务就绪...

🧪 Step 4/4: 运行进阶特性演示...

--- 单条推理 (v1, ×2) ---
{"result": 10}

--- 批量推理 (4 条并发请求，自动 batch) ---
{"result": 2}
{"result": 4}
{"result": 6}
{"result": 8}

--- Prometheus 指标 ---
lightserver_inference_duration_seconds_bucket{model="advanced_model",le="0.01"} 5
advanced_model_requests_total 5

--- 切换到 v2 (+100) ---
{"success": true, "message": "Loaded version 2"}

--- 版本切换后推理 ---
{"result": 105}

🛑 停止服务...
✅ 完成！
```

## 启动服务

```bash
cd examples/02_advanced
light-server serve --config server.yaml
```

## 单条推理

```bash
curl -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}'
```

v1 预期输出（乘法 x2）：

```json
{"result": 10}
```

## 批处理推理

由于 `max_batch_size: 4`，服务器会自动将多个请求合并为一批。发送多个并行请求即可触发：

```bash
for i in 1 2 3 4; do
  curl -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
    -H "Content-Type: application/json" \
    -d "{\"input\": $i}" &
done
wait
```

## 查看自定义指标

```bash
curl http://127.0.0.1:8002/metrics | grep advanced_model
```

可看到：

- `advanced_model_requests_total` — 请求计数
- `advanced_model_predict_seconds_bucket` — 延迟分布

## 热重载

`config.yaml` 中启用了 `hot_reload: true`。修改 `model_repo/advanced_model/1/model.py` 中的 `multiplier` 值并保存，服务器会自动重新加载模型，无需重启。

## 切换版本

```bash
# 加载 v2（加法运算）
curl -X POST http://127.0.0.1:8000/v2/repository/models/advanced_model/load \
  -H "Content-Type: application/json" \
  -d '{"version": "2"}'

# 推理验证
curl -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}'
```

v2 预期输出（加法 +100）：

```json
{"result": 105}
```
