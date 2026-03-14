#!/bin/bash
# =====================================================
# 内河航运平台启动脚本
# =====================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

echo "=================================================="
echo "  中国内河航运数据采集与分析平台"
echo "=================================================="

# 检查Python
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 创建虚拟环境（如不存在）
if [ ! -d ".venv" ]; then
    echo "[INFO] 创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
echo "[INFO] 安装/更新依赖..."
pip install -q -r requirements.txt

# 设置ANTHROPIC_API_KEY提示
if [ -z "$ANTHROPIC_API_KEY" ] && grep -q "your-anthropic-api-key-here" .env 2>/dev/null; then
    echo ""
    echo "[WARN] 未配置 ANTHROPIC_API_KEY，AI解析功能将降级为规则匹配模式。"
    echo "       请编辑 .env 文件，填入真实的 Anthropic API Key 以启用完整AI能力。"
    echo ""
fi

echo "[INFO] 启动服务..."
echo "[INFO] 服务地址: http://localhost:8000"
echo "[INFO] API文档:  http://localhost:8000/docs"
echo "[INFO] 默认账号: admin / Admin@2026"
echo ""

# 启动
uvicorn main:app --reload --host 0.0.0.0 --port 8000
