# light_server 多进程 HTTP 改造计划

## 目标

将 light_server 从单进程 HTTP（`uvicorn workers=1`）改造为**多进程 HTTP Worker + 主进程协调**架构，与 LitServe 的 `num_api_servers` 模式对齐，HTTP 吞吐达到 LitServe 同等水平，同时保留所有现有特性。

## 根因分析

LitServe 默认启动 `num_api_servers`（等于 inference worker 数量）个 uvicorn 进程，HTTP 请求解析和响应序列化并行化。

light_server 强制 `workers=1`，所有 HTTP 处理（JSON 解析、路由、registry 查询、response 等待）在单 Python 进程内，GIL 和锁竞争是瓶颈。

| 维度 | LitServe | light_server (当前) |
|------|----------|---------------------|
| HTTP 进程 | N 个 uvicorn | `workers=1` |
| Transport consumer | `num_consumers = N` | `num_consumers = 1` |
| Response buffer | 每进程独立 | 全局单点 + TTL 线程 + 锁 |
| Registry | `mp.Manager().dict()` | `threading.Lock` + dict |

## 架构设计

```
[主进程: LightServer]
  ├── ModelManager (load/unload, 维护 worker 进程生命周期)
  ├── Registry (mp.Manager().dict() — 跨进程共享)
  ├── Transport (N consumer queues / 或 ZMQ)
  ├── Admin Queue (接收 HTTP Worker 的 load/unload 请求)
  ├── Admin Loop Thread (处理 admin 请求)
  ├── Poll / Metrics / gRPC
  └── 启动 N 个 HTTP Worker 进程

[HTTP Worker 0]      [HTTP Worker 1]     ...    [HTTP Worker N-1]
  ├── uvicorn          ├── uvicorn                ├── uvicorn
  ├── response_buffer  ├── response_buffer        ├── response_buffer (每进程独立)
  ├── response_consumer(consumer_id=0) ├── consumer_id=1        ├── consumer_id=N-1
  ├── _litapi_hooks    ├── _litapi_hooks          ├── _litapi_hooks (按需加载)
  └── infer() → worker_queue ─────────────────────────────────→ [Inference Worker Pool]
```

## CLI 影响分析

| 命令 | 是否受影响 | 说明 |
|------|-----------|------|
| `serve` | **仅内部实现** | CLI 接口（参数、用法、输出）完全不变，新增 `--http-workers` 可选参数 |
| `config-check` | 否 | 只读 YAML，不启动服务器 |
| `benchmark` | 否 | HTTP 客户端，API 不变则零感知 |
| `analyze` | 否 | 独立分析工具 |
| `pack` | 否 | 独立文件打包 |
| `unpack` | 否 | 独立文件解包 |
| `init` | 否 | 项目模板生成器 |

## 改动文件清单

### 里程碑 1：核心基础设施

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/light_server/config.py` | 修改 | `ServerConfig` 添加 `http_workers: int \| None = None` |
| `src/light_server/core/registry.py` | 修改 | 改用 `mp.Manager().dict()` 实现进程安全 |
| `src/light_server/core/model_manager.py` | 修改 | 锁进程安全化、uid 无锁化、提取 `infer()` 逻辑、注册时增加 `model_dir` |
| `src/light_server/cli.py` | 修改 | `_serve_args()` 新增 `--http-workers` 可选参数 |

### 里程碑 2：多进程 HTTP

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/light_server/http/state.py` | **新增** | `HTTPState`：每进程轻量级状态，含 response_buffer、hook 缓存、infer 逻辑 |
| `src/light_server/http/worker.py` | **新增** | HTTP Worker 进程入口 `http_worker_main()` |
| `src/light_server/http/handlers.py` | 修改 | `server: LightServer` → `state: HTTPState`，response_queue_id 动态 |
| `src/light_server/http/admin.py` | 修改 | load/unload 走 admin_queue IPC，其余本地处理 |
| `src/light_server/http/app.py` | 修改 | `create_app(server)` → `create_app(state)` |
| `src/light_server/core/server.py` | 修改 | 主进程职责：启动 HTTP Workers、admin loop、gRPC、metrics |

### 里程碑 3：周边适配

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `src/light_server/webui/routes.py` | 修改 | `_job_store` → `Manager().dict()`，`_benchmark_running` → `Manager().Value`，load/unload 走 IPC |
| `src/light_server/grpc/servicer.py` | 修改 | 改用提取后的公共 `infer()`，response buffer 改为进程本地 |

## 关键设计决策

### 1. Registry 进程安全

- `_registry`、`_active_versions`、`_queues`、`_worker_queues` 全部使用 `Manager().dict()`
- Worker queue 创建改用 `Manager().Queue()`（可存入 Manager.dict）
- Manager 内部已同步，不需要显式锁

### 2. Response Buffer

- 移除全局 `TTLResponseBuffer`
- 每个 HTTP Worker 进程内维护 `dict[str, ResponseBufferItem]`
- 超时由 `asyncio.wait_for(event.wait(), timeout=...)` 处理

### 3. Admin IPC

只有涉及 inference worker **进程生命周期**的操作需要 IPC：
- `load` → 创建 `mp.Process`
- `unload` → 终止进程

其余操作（activate、list、is_ready、文件上传）直接在 HTTP Worker 本地处理：
- activate → 修改 `Manager.dict()`，全局立即生效
- 只读查询 → 读取共享 Registry
- 文件操作 → 各进程独立访问文件系统

### 4. LitAPI Hook（on_request / on_response）

- 每个 HTTP Worker 进程按需加载 LitAPI 实例（仅用于 hooks）
- 通过 Registry 中的 `model_dir` 动态 `load_litapi_from_file()`
- 内存占用可控（只加载定义了 hook 的模型）

### 5. 日志

- `_log_queue` 改为 `Manager().Queue()`
- 所有进程（主进程 + HTTP Workers + Inference Workers）日志发送到同一 queue
- `LogConsumer` 单线程消费写入同一文件，不会混乱或缺失

## 实施顺序

### 里程碑 1：核心基础设施
1. `config.py` — 添加 `http_workers`
2. `registry.py` — Manager 化
3. `model_manager.py` — 锁改造、uid 无锁化、提取 infer 逻辑
4. `cli.py` — 新增 `--http-workers` 参数

验证：`uv run pytest tests/ -v` 全部通过

### 里程碑 2：多进程 HTTP
1. `http/state.py` — 新增 `HTTPState`
2. `http/worker.py` — 新增 HTTP Worker 入口
3. `http/handlers.py` — 适配 HTTPState
4. `http/admin.py` — load/unload 走 IPC
5. `http/app.py` — 重构 create_app
6. `core/server.py` — 多进程启动逻辑

验证：多 Worker 启动，并发请求正常响应

### 里程碑 3：周边适配
1. `webui/routes.py` — 状态共享 + admin IPC
2. `grpc/servicer.py` — 改用公共 infer

验证：WebUI + gRPC + benchmark 全链路通过

### 里程碑 4：性能基准（可选）
1. MPQueueTransport → ZMQTransport
2. `wrk` / `light-server benchmark` 对比测试

## 风险点

| 风险 | 应对 |
|------|------|
| `Manager().Queue()` 比 `mp.Queue()` 慢 | 阶段 4 升级到 ZMQTransport |
| LitAPI hook 实例内存占用 | 仅加载定义了 hook 的模型 |
| macOS spawn + fd 传递 | uvicorn 内置 `fd` 参数支持 |
| 多进程日志时序微偏 | 每条日志含 `process`/`processName` 字段 |
| Admin IPC 延迟 | admin 低频操作，1-5ms 可接受 |
