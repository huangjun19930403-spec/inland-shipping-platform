# 货源 AI 本地调试说明

日期：2026-05-07

## 前置条件

本地调试前先完成建表和 seed：

```bash
alembic upgrade head
python -m scripts.seed_system_init
```

必须配置以下环境变量或系统配置：

```bash
export DASHSCOPE_API_KEY="你的百炼 API Key"
export DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export DASHSCOPE_FAST_MODEL="qwen-turbo"
export DASHSCOPE_MODEL="qwen-plus"
export DASHSCOPE_STREAM_TIMEOUT_SECONDS="120"
export DASHSCOPE_STRONG_REVIEW_ENABLED="true"
export FREIGHT_AI_STALE_HEARTBEAT_SECONDS="180"
```

说明：

- `DASHSCOPE_FAST_MODEL` 用于 AI 线索切分和字段抽取。
- `DASHSCOPE_MODEL` 用于低置信度候选的强模型复核。
- 当前主链路使用 DashScope SDK 流式调用，不再以 LangChain 作为主调用入口。
- 微信原文拆解必须由 AI 完成，后端不会用正则、关键词或本地规则切分微信群原文。

## 方式一：Celery eager 单机调试

适合本机快速验证，不需要 Redis worker：

```bash
export ANALYSIS_CELERY_EAGER=true
uvicorn main:app --reload
```

前端点击“微信采集 -> 提交解析”后，任务会在 API 进程内同步执行 Celery eager 任务，仍会经历 `QUEUED -> PARSING -> PARSED/FAILED` 状态。
批次详情会持续更新解析阶段、进度百分比、心跳时间和 AI 耗时。

## 方式二：Redis + Celery worker

贴近生产异步链路：

```bash
redis-server
celery -A app.tasks.celery_app:celery_app worker -Q freight_ai,analysis -l info
uvicorn main:app --reload
```

解析接口只负责投递任务，前端轮询批次详情等待结果。复杂微信群文本不会占用 HTTP 请求直到 AI 返回；worker 会在 DashScope 流式输出期间刷新心跳。

## 直接调试解析链

使用内置真实微信群样例：

```bash
python -m scripts.debug_freight_ai_parse --sample
```

读取本地文本文件：

```bash
python -m scripts.debug_freight_ai_parse --file /tmp/wechat_freight.txt
```

输出内容包括：

- AI 解析出的结构化线索。
- AI 判断出的联系人、公共备注、可发状态和上下文继承结果。
- 装卸地、标准货品的本地匹配建议。
- `READY`、`DEFERRED`、`FULL`、`UNKNOWN` 可发状态和人工处理原因。

该脚本不会写入 `freight_clue` 或 `freight_candidate`，可安全反复调试。
