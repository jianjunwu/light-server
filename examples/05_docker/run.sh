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

echo -e "${BLUE}🚀 Step 2/4: 启动 light-server (本地模式)...${NC}"
light-server serve --config server.yaml &
SERVER_PID=$!

echo -e "${BLUE}⏳ Step 3/4: 等待服务就绪...${NC}"
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/v2/models/demo_model/ready > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
echo ""

echo -e "${BLUE}🧪 Step 4/4: 发送推理请求...${NC}"
echo ""

echo -e "${YELLOW}--- 推理请求 ---${NC}"
curl -s -X POST http://127.0.0.1:8000/v2/models/demo_model/infer \
  -H "Content-Type: application/json" \
  -d '{"text": "This is a great and amazing product"}' | python3 -m json.tool

echo ""
echo -e "${YELLOW}--- Prometheus 指标 ---${NC}"
curl -s http://127.0.0.1:8002/metrics | grep demo_model || echo "(no metrics yet)"

echo ""
echo -e "${BLUE}🛑 停止服务...${NC}"
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo -e "${GREEN}✅ 完成！${NC}"
echo ""
echo "💡 Docker 部署: docker-compose up --build"
