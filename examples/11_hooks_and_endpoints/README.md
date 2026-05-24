# 11_hooks_and_endpoints — 模型生命周期 Hooks + 动态端点

演示 LitAPI 的三个生命周期 hooks（`on_request`、`on_response`、`health_check`）以及通过 `model_repo/*_endpoint.py` 文件自定义全局 HTTP 端点。

## 目录结构

```
model_repo/
  hook_model/
    1/
      model.py       # 含 on_request / on_response / health_check 的 LitAPI
      config.yaml
  health_endpoint.py # 自定义全局 /health
  status_endpoint.py # 自定义 /status 端点
```

## 🎯 30 秒体验

```bash
cd examples/11_hooks_and_endpoints
./run.sh
```

终端会自动完成：启动服务 → 等待就绪 → 演示自定义 /health → /status → 模型就绪检查 → 推理请求 → 停止服务。

## 📸 运行效果

```
--- 自定义全局 /health ---
{
    "custom_health": true,
    "loaded_models": 1,
    "status": "ok",
    "uptime_seconds": 0.12
}

--- 自定义 /status 端点 ---
{
    "loaded_models": ["hook_model"],
    "loaded_models_count": 1,
    "server": "light-server"
}

--- 模型就绪检查（含 health_check） ---
{
    "active_version": "1",
    "model_status": {
        "device": "cpu",
        "status": "healthy",
        "uptime_requests": 0
    },
    "name": "hook_model",
    "ready": true,
    "version": "1"
}

--- 推理请求（on_request 注入 _auth，on_response 注入 _meta） ---
{
    "_meta": {
        "latency_ms": 12.34,
        "model_name": "hook_model",
        "status": "ok",
        "version": "1"
    },
    "result": 42
}
```

## 核心特性详解

### 1. 模型级 Hooks（LitAPI 子类中定义）

在 `model.py` 的 LitAPI 子类中可选实现三个 hook：

| Hook | 调用时机 | 用途 |
|------|---------|------|
| `on_request(payload, request_meta)` | 主进程收到请求、入队 **之前** | 输入预处理、鉴权、注入上下文 |
| `on_response(response, response_meta)` | 主进程收到 worker 响应、返回 **之前** | 输出后处理、附加元数据、签名 |
| `health_check()` | `GET /v2/models/{name}/ready` | 自定义模型级健康状态 |

**`request_meta` 包含：**
- `headers` — 请求头字典
- `query_params` — URL 查询参数
- `client_host` — 客户端 IP
- `method` — HTTP 方法
- `url` — 完整请求 URL
- `path_params` — `model_name` / `version`

**`response_meta` 包含：**
- `model_name` / `version`
- `request_meta` — 上游注入的原始元数据
- `status` — `"ok"` 或 `"error"`

> 所有 hooks 都是**可选**的。如果未实现，服务行为与标准 LitAPI 完全一致。

### 2. 动态端点（`model_repo/*_endpoint.py`）

在 `model_repo` 根目录放置 `*_endpoint.py` 文件即可自动注册为 FastAPI 路由：

```python
# health_endpoint.py
def handler(request, server):
    return {"status": "ok", "custom": True}
```

注册为 `GET /health`。**如果文件名是 `health_endpoint.py`，则会覆盖默认的 `/health`。**

支持可选的 `methods` 变量：

```python
# webhook_endpoint.py
methods = ["POST"]

def handler(request, server):
    return {"webhook": True}
```

也支持 `async def handler`：

```python
# status_endpoint.py
async def handler(request, server):
    return {"async": True}
```

**命名规则：** 文件名去掉 `_endpoint.py` 后缀即为路由路径。
- `health_endpoint.py` → `/health`
- `status_endpoint.py` → `/status`
- `webhook_endpoint.py` → `/webhook`

### 3. 启动服务

```bash
cd examples/11_hooks_and_endpoints
light-server serve --config server.yaml
```

### 4. 手动测试

```bash
# 自定义全局 health
curl http://127.0.0.1:8000/health

# 自定义 status 端点
curl http://127.0.0.1:8000/status

# 模型就绪检查（含 health_check）
curl http://127.0.0.1:8000/v2/models/hook_model/ready

# 推理（携带 auth header，触发 on_request + on_response）
curl -X POST http://127.0.0.1:8000/v2/models/hook_model/infer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-token" \
  -d '{"input": 21}'
```
