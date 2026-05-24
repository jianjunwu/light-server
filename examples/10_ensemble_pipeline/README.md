# 10_ensemble_pipeline — Ensemble 流水线编排

演示 light-server 的 Ensemble 功能：通过 DAG 定义多模型流水线，层内并行、层间串行，无需编写客户端串联代码。

## 流水线逻辑

```
输入 x
  ├──→ square(x) = x²    ──┐
  └──→ double(x) = 2x    ──┤
                            ↓
                      combine(a, b) = a + b
                              = x² + 2x
```

- **Layer 0（并行）**：`square` 和 `double` 同时执行
- **Layer 1**：`combine` 等待前两步完成后执行

## 目录结构

```
model_repo/
  square/              # 子模型：平方运算
    model_config.yaml
    1/
      model.py
      config.yaml
  double/              # 子模型：翻倍运算
    model_config.yaml
    1/
      model.py
      config.yaml
  combine/             # 子模型：求和运算
    model_config.yaml
    1/
      model.py
      config.yaml
  math_pipeline/       # Ensemble 定义（无需 model.py）
    1/
      config.yaml      # DAG + 步骤引用
server.yaml            # 服务端配置
client.py              # 客户端：调用 ensemble
run.sh                 # 一键运行
test_model.py          # 模型逻辑验证
```

## 🎯 30 秒体验

```bash
cd examples/10_ensemble_pipeline
./run.sh
```

终端会自动完成：验证模型逻辑 → 启动服务 → 调用 ensemble → 验证子模型 → 停止服务。

## 📸 运行效果

```
==================================================
  Ensemble Pipeline Demo
  Pipeline: square(x) + double(x) = x^2 + 2x
==================================================

  Single inference:
  math_pipeline(5) = 35  (expected: 35)

  Multiple inputs:
    math_pipeline(1) =   3  (expected: 3)
    math_pipeline(2) =   8  (expected: 8)
    math_pipeline(3) =  15  (expected: 15)
    math_pipeline(4) =  24  (expected: 24)
    math_pipeline(10) = 120  (expected: 120)

  Individual sub-models:
    square(5)    = 25  (expected: 25)
    double(5)    = 10  (expected: 10)
    combine(25,10) = 35  (expected: 35)

==================================================
  All tests passed!
==================================================
```

## 启动服务

```bash
cd examples/10_ensemble_pipeline
light-server serve --config server.yaml
```

## 调用 Ensemble

```bash
curl -X POST http://127.0.0.1:8000/v2/models/math_pipeline/infer \
  -H "Content-Type: application/json" \
  -d '{"x": 5}'
```

预期输出：

```json
{"result": 35}
```

## 分步调用（验证子模型）

```bash
# square
curl -X POST http://127.0.0.1:8000/v2/models/square/infer \
  -d '{"x": 5}'
# {"result": 25}

# double
curl -X POST http://127.0.0.1:8000/v2/models/double/infer \
  -d '{"x": 5}'
# {"result": 10}

# combine
curl -X POST http://127.0.0.1:8000/v2/models/combine/infer \
  -d '{"a": 25, "b": 10}'
# {"result": 35}
```

## Ensemble 配置详解

**`model_repo/math_pipeline/1/config.yaml`：**

```yaml
name: math_pipeline
ensemble:
  steps:
    - name: square
      model: square
      version: "1"
      inputs:
        x: "$request.x"

    - name: double
      model: double
      version: "1"
      inputs:
        x: "$request.x"

    - name: combine
      model: combine
      version: "1"
      inputs:
        a: "$square.result"
        b: "$double.result"
```

- `$request.x` — 从原始请求中读取字段 `x`
- `$square.result` — 从 `square` 步骤的输出中读取字段 `result`
- `square` 和 `double` 无相互依赖 → **并行执行**
- `combine` 依赖前两步 → 等待它们完成后再执行

## 管理 API

```bash
# 查看 ensemble 状态
curl http://127.0.0.1:8000/v2/models/math_pipeline

# 查看所有已加载模型
curl http://127.0.0.1:8000/v2/models

# 查看指标（含 ensemble 步骤延迟）
curl http://127.0.0.1:8002/metrics | grep ensemble
```

## 扩展思路

- **顺序链**：将 `double` 改为依赖 `$square.result`，形成纯串行流水线
- **更多并行分支**：添加 `cube`、`sqrt` 等分支，在 `combine` 中合并更多输入
- **条件路由**：在 `combine` 模型内部根据输入值选择不同的下游路径
- **版本切换**：`math_pipeline` 的 `version: "1"` 可改为引用不同版本的子模型，实现 A/B 测试
