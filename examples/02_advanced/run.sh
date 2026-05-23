#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🔧 Step 1/4: 验证模型逻辑...${NC}"
python3 test_model.py
echo ""

echo -e "${BLUE}🚀 Step 2/4: 启动 light-server...${NC}"
light-server serve --config server.yaml &
SERVER_PID=$!

echo -e "${BLUE}⏳ Step 3/4: 等待服务就绪...${NC}"
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/v2/models/advanced_model/ready > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
echo ""

echo -e "${BLUE}🧪 Step 4/4: 运行进阶特性演示...${NC}"
echo ""

echo -e "${YELLOW}--- 单条推理 (v1, ×2) ---${NC}"
curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}' | python3 -m json.tool

echo ""
echo -e "${YELLOW}--- 批量推理 (4 条并发请求，自动 batch) ---${NC}"
for i in 1 2 3 4; do
  curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
    -H "Content-Type: application/json" \
    -d "{\"input\": $i}" &
done
wait
echo ""

echo -e "${YELLOW}--- Prometheus 指标 ---${NC}"
curl -s http://127.0.0.1:8002/metrics | grep advanced_model || echo "(no metrics yet)"

echo ""
echo -e "${YELLOW}--- 切换到 v2 (+100) ---${NC}"
curl -s -X POST http://127.0.0.1:8000/v2/repository/models/advanced_model/load \
  -H "Content-Type: application/json" \
  -d '{"version": "2"}' | python3 -m json.tool

echo ""
echo -e "${YELLOW}--- 版本切换后推理 ---${NC}"
curl -s -X POST http://127.0.0.1:8000/v2/models/advanced_model/infer \
  -H "Content-Type: application/json" \
  -d '{"input": 5}' | python3 -m json.tool

echo ""
echo -e "${BLUE}🛑 停止服务...${NC}"
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo -e "${GREEN}✅ 完成！${NC}"
