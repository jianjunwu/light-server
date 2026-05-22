[English](../en/05_cli_reference.md) | 简体中文

# CLI 命令参考

```
light-server [command] [options]
```

## 命令速查表

| 命令 | 说明 |
|------|------|
| `serve` | 启动推理服务 |
| `config-check` | 校验 YAML 配置文件 |
| `benchmark` | 对运行中的服务执行性能压测 |
| `analyze` | 运行模型分析器，寻找最优配置 |
| `pack` | 将模型目录打包为 `.lma` 制品 |
| `unpack` | 解包 `.lma` 制品 |

---

## serve

启动推理服务。

### 使用配置文件启动

```bash
light-server serve --config server.yaml
```

### 内联模式启动（无需配置文件）

```bash
light-server serve my_module:MyAPI --port 8000
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `module` | str | — | Python 模块路径，格式 `module:Class` |
| `--config, -c` | str | — | YAML 配置文件路径 |
| `--port` | int | `8000` | HTTP 端口 |
| `--host` | str | `0.0.0.0` | 监听地址 |
| `--accelerator` | str | `auto` | 加速器 |
| `--devices` | str | `auto` | 设备数 |
| `--workers-per-device` | int | `1` | 每设备工作进程数 |
| `--timeout` | float | `30.0` | 请求超时（秒） |
| `--log-level` | str | `info` | 日志级别 |
| `--log-dir` | str | — | 日志目录（自动生成 info.log + error.log） |
| `--log-info` | str | — | info 日志文件路径 |
| `--log-error` | str | — | error 日志文件路径 |
| `--log-format` | str | `json` | 日志格式：`json`/`text` |
| `--log-rotate-by` | str | `none` | 轮转策略：`none`/`size`/`time` |
| `--log-max-size` | int | `100` | 单日志文件最大 MB（size 模式） |
| `--log-when` | str | `midnight` | 轮转时间（time 模式） |
| `--log-backup-count` | int | `7` | 保留的备份日志数 |
| `--model-repo` | str | `./model_repo` | 模型仓库路径 |
| `--grpc-port` | int | `8001` | gRPC 端口 |
| `--metrics-port` | int | `8002` | 指标端口 |
| `--no-grpc` | flag | — | 禁用 gRPC |
| `--no-metrics` | flag | — | 禁用指标 |

---

## config-check

校验配置文件语法和字段。

```bash
light-server config-check server.yaml
```

输出示例：

```
Configuration OK: server.yaml
  HTTP port: 8000
  gRPC port: 8001
  Metrics port: 8002
  Model repo: ./model_repo
  Load models: ['test_model']
```

---

## benchmark

对运行中的服务执行压测。

```bash
light-server benchmark --model test_model --duration 30
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--url` | str | `http://127.0.0.1:8000` | 服务地址 |
| `--model` | str | **必填** | 模型名称 |
| `--version` | str | `null` | 模型版本 |
| `--concurrency` | int | `8` | 并发请求数 |
| `--duration` | float | `30.0` | 压测时长（秒） |
| `--mode` | str | `fixed` | 负载模式：`fixed`/`ramp` |
| `--max-concurrency` | int | `64` | ramp 模式最大并发 |
| `--step-duration` | float | `10.0` | ramp 每步时长（秒） |
| `--payload` | str | `'{"input": 1.0}'` | 请求负载（JSON 字符串） |
| `--output` | str | — | 结果输出 JSON 文件 |

### 输出示例

```
Benchmark Results (test_model):
  Mode:            fixed
  Duration:        30s
  Total requests:  15000
  Success:         15000
  Failed:          0
  Throughput:      500.0 req/s
  Latency (ms):
    mean: 15.2
    p50:  14.0
    p90:  20.0
    p99:  35.0
    p99.9:50.0
```

---

## analyze

运行模型分析器，自动搜索最优批大小、超时时间和并发配置。

```bash
light-server analyze --model test_model --output-dir ./reports
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--model-repo` | str | `./model_repo` | 模型仓库路径 |
| `--model` | str | **必填** | 模型名称 |
| `--output-dir` | str | `./reports` | 报告输出目录 |

输出：

```
Analysis complete. Pareto optimal configurations: 12
```

报告保存在 `./reports/{model_name}/analysis_report.json`。

---

## pack

将模型目录打包为 `.lma`（Light Model Artifact）制品。

```bash
light-server pack model_repo/test_model --version 1.0.0
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `model_dir` | str | **必填** | 模型目录路径 |
| `--version, -v` | str | **必填** | 版本号（语义化版本） |
| `--output, -o` | str | `./artifacts` | 输出目录 |
| `--build-id` | str | 自动生成 | 构建 ID |
| `--sign-key` | str | — | Ed25519 私钥 PEM 路径 |
| `--signer` | str | — | 签名者身份 |
| `--ignore` | str | — | 额外忽略模式（可重复） |

---

## unpack

解包 `.lma` 制品。

```bash
light-server unpack artifact.lma --to ./model_repo
```

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `artifact` | str | **必填** | `.lma` 文件路径 |
| `--to` | str | `.` | 解压目标目录 |
| `--verify-key` | str | — | Ed25519 公钥 PEM 路径 |
| `--dry-run` | flag | — | 仅校验，不解压 |

---

## 下一步

- [运维指南](06_operations.md)
- [FAQ](08_faq.md)
