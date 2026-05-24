#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}🚀 Step 1/3: 启动 light-server...${NC}"
light-server serve --config server.yaml &
SERVER_PID=$!

echo -e "${BLUE}⏳ Step 2/3: 等待服务就绪...${NC}"
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/v2/models/hook_model/ready > /dev/null 2>&1; then
        break
    fi
    sleep 0.5
done
echo ""

echo -e "${BLUE}🧪 Step 3/3: 演示 hooks 与动态端点...${NC}"
echo ""

echo -e "${YELLOW}--- 自定义全局 /health ---${NC}"
curl -s http://127.0.0.1:8000/health | python3 -m json.tool
echo ""

echo -e "${YELLOW}--- 自定义 /status 端点 ---${NC}"
curl -s http://127.0.0.1:8000/status | python3 -m json.tool
echo ""

echo -e "${YELLOW}--- 模型就绪检查（含 health_check） ---${NC}"
curl -s http://127.0.0.1:8000/v2/models/hook_model/ready | python3 -m json.tool
echo ""

echo -e "${YELLOW}--- 推理请求（on_request 注入 _auth，on_response 注入 _meta） ---${NC}"
curl -s -X POST http://127.0.0.1:8000/v2/models/hook_model/infer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer demo-token" \
  -d '{"input": 21}' | python3 -m json.tool
echo ""

echo -e "${BLUE}🛑 停止服务...${NC}"
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

echo -e "${GREEN}✅ 完成！${NC}"
