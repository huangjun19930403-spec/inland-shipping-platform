# 生产部署指南

**项目：中国内河航运数据采集与分析平台 V2.0**
**推荐部署方案：Docker Compose + PostgreSQL + Redis + Nginx**

---

## 目录

1. [部署架构总览](#1-部署架构总览)
2. [服务器要求](#2-服务器要求)
3. [Docker Compose部署（推荐）](#3-docker-compose部署推荐)
4. [手动部署（裸机）](#4-手动部署裸机)
5. [数据库配置](#5-数据库配置)
6. [Celery任务队列配置](#6-celery任务队列配置)
7. [Nginx反向代理配置](#7-nginx反向代理配置)
8. [环境变量说明](#8-环境变量说明)
9. [数据库迁移](#9-数据库迁移)
10. [监控与运维](#10-监控与运维)
11. [安全加固](#11-安全加固)
12. [故障排查](#12-故障排查)

---

## 1. 部署架构总览

```
                        ┌──────────────────────────────┐
                        │         Internet             │
                        └──────────────┬───────────────┘
                                       │ HTTPS 443
                        ┌──────────────▼───────────────┐
                        │     Nginx（反向代理/SSL）      │
                        └──────────────┬───────────────┘
                                       │ HTTP 8000
              ┌────────────────────────▼──────────────────────────┐
              │              FastAPI Application                   │
              │         (Uvicorn + Gunicorn Workers)               │
              └─────────────┬─────────────────────┬───────────────┘
                            │                     │
              ┌─────────────▼──────┐  ┌───────────▼──────────────┐
              │   PostgreSQL DB    │  │     Redis                │
              │   (持久化存储)     │  │  (Celery Broker/Backend) │
              └────────────────────┘  └──────────────────────────┘
                                                │
              ┌─────────────────────────────────▼────────────────┐
              │            Celery Workers                         │
              │  Worker: ai队列    Worker: analysis队列           │
              └────────────────────────────────────────────────────┘
              ┌─────────────────────────────────────────────────┐
              │          Celery Beat（定时调度）                  │
              └────────────────────────────────────────────────────┘
```

**服务清单：**

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx | 80/443 | 反向代理、SSL终止、静态文件 |
| FastAPI | 8000 | 主应用（内部，不对外暴露） |
| PostgreSQL | 5432 | 主数据库（内部） |
| Redis | 6379 | Celery消息队列（内部） |
| Celery Worker | - | AI任务执行器 |
| Celery Beat | - | 定时任务调度器 |

---

## 2. 服务器要求

### 最低配置（小型部署）

| 资源 | 最低 | 推荐 |
|------|------|------|
| CPU | 2核 | 4核 |
| 内存 | 4GB | 8GB |
| 磁盘 | 40GB SSD | 100GB SSD |
| 系统 | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

### 中型部署（日活100+用户）

| 资源 | 配置 |
|------|------|
| CPU | 8核 |
| 内存 | 16GB |
| 磁盘 | 500GB SSD |
| 网络 | 100Mbps |

> **Claude API说明：** AI解析依赖Anthropic Claude API（云服务），服务器需能访问 `api.anthropic.com`（443端口）。

---

## 3. Docker Compose部署（推荐）

### 3.1 安装Docker和Docker Compose

```bash
# Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
sudo apt install -y docker-compose-plugin

# 验证安装
docker --version
docker compose version
```

### 3.2 创建部署目录结构

```bash
mkdir -p /opt/inland-shipping
cd /opt/inland-shipping
git clone https://github.com/huangjun19930403-spec/inland-shipping-platform.git app
cd app
```

### 3.3 创建 `docker-compose.yml`

在项目根目录创建 `docker-compose.yml`：

```yaml
version: '3.9'

services:
  # ─── PostgreSQL数据库 ───────────────────────────
  db:
    image: postgres:15-alpine
    container_name: inland_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: inland_shipping
      POSTGRES_USER: inland_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U inland_user -d inland_shipping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - inland_net

  # ─── Redis ─────────────────────────────────────
  redis:
    image: redis:7-alpine
    container_name: inland_redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    networks:
      - inland_net

  # ─── FastAPI主应用 ──────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: inland_api
    restart: unless-stopped
    env_file: .env.production
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    ports:
      - "8000:8000"
    volumes:
      - ./logs:/app/logs
    networks:
      - inland_net
    command: gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
             --bind 0.0.0.0:8000 --timeout 120 --access-logfile -

  # ─── Celery AI Worker ───────────────────────────
  celery-ai:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: inland_celery_ai
    restart: unless-stopped
    env_file: .env.production
    depends_on:
      - db
      - redis
    networks:
      - inland_net
    command: celery -A app.tasks.celery_app worker
             --loglevel=info -Q ai --concurrency=2

  # ─── Celery Analysis Worker ─────────────────────
  celery-analysis:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: inland_celery_analysis
    restart: unless-stopped
    env_file: .env.production
    depends_on:
      - db
      - redis
    networks:
      - inland_net
    command: celery -A app.tasks.celery_app worker
             --loglevel=info -Q analysis --concurrency=1

  # ─── Celery Beat调度器 ───────────────────────────
  celery-beat:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: inland_celery_beat
    restart: unless-stopped
    env_file: .env.production
    depends_on:
      - redis
    networks:
      - inland_net
    command: celery -A app.tasks.celery_app beat
             --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler

  # ─── Nginx ─────────────────────────────────────
  nginx:
    image: nginx:alpine
    container_name: inland_nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./logs/nginx:/var/log/nginx
    depends_on:
      - api
    networks:
      - inland_net

volumes:
  postgres_data:
  redis_data:

networks:
  inland_net:
    driver: bridge
```

### 3.4 创建 `Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install gunicorn

# 复制项目代码
COPY . .

# 创建日志目录
RUN mkdir -p logs

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", "--timeout", "120"]
```

### 3.5 配置生产环境变量

创建 `.env.production`（**不提交到Git！**）：

```bash
# 复制模板
cp .env .env.production
# 编辑生产配置
vim .env.production
```

关键配置（见第8章完整说明）：

```env
DEBUG=false
DATABASE_URL=postgresql+asyncpg://inland_user:${POSTGRES_PASSWORD}@db:5432/inland_shipping
CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
CELERY_RESULT_BACKEND=redis://:${REDIS_PASSWORD}@redis:6379/1
SECRET_KEY=<生成强随机密钥，见下方>
ANTHROPIC_API_KEY=sk-ant-xxxx
```

生成强密钥：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 3.6 首次部署

```bash
cd /opt/inland-shipping/app

# 构建镜像
docker compose build

# 启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 执行数据库迁移
docker compose exec api alembic upgrade head

# 初始化种子数据
docker compose exec api python -m scripts.seed_data

# 查看应用日志
docker compose logs -f api
```

### 3.7 更新部署

```bash
cd /opt/inland-shipping/app

# 拉取最新代码
git pull origin main

# 重新构建并部署（零停机滚动更新）
docker compose build api celery-ai celery-analysis celery-beat
docker compose up -d --no-deps api celery-ai celery-analysis celery-beat

# 执行新迁移（如果有）
docker compose exec api alembic upgrade head
```

---

## 4. 手动部署（裸机）

适用于无法使用Docker的环境。

### 4.1 安装Python环境

```bash
# Ubuntu 22.04
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev \
                    libpq-dev gcc nginx postgresql redis-server

# 创建项目用户
sudo useradd -m -s /bin/bash inland
sudo su - inland
```

### 4.2 部署应用

```bash
# 克隆代码
git clone <repo_url> /home/inland/app
cd /home/inland/app

# 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt gunicorn

# 配置环境变量
cp .env .env.production
# 编辑 .env.production，配置生产数据库等
```

### 4.3 配置Systemd服务

创建 `/etc/systemd/system/inland-api.service`：

```ini
[Unit]
Description=Inland Shipping Platform API
After=network.target postgresql.service redis.service

[Service]
Type=exec
User=inland
WorkingDirectory=/home/inland/app
Environment="PATH=/home/inland/app/.venv/bin"
EnvironmentFile=/home/inland/app/.env.production
ExecStart=/home/inland/app/.venv/bin/gunicorn main:app \
    -w 4 -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 --timeout 120 \
    --access-logfile /var/log/inland/access.log \
    --error-logfile /var/log/inland/error.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

创建 `/etc/systemd/system/inland-celery-ai.service`：

```ini
[Unit]
Description=Inland Shipping Celery AI Worker
After=network.target redis.service

[Service]
Type=exec
User=inland
WorkingDirectory=/home/inland/app
Environment="PATH=/home/inland/app/.venv/bin"
EnvironmentFile=/home/inland/app/.env.production
ExecStart=/home/inland/app/.venv/bin/celery \
    -A app.tasks.celery_app worker \
    --loglevel=info -Q ai --concurrency=2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo mkdir -p /var/log/inland
sudo chown inland:inland /var/log/inland

sudo systemctl daemon-reload
sudo systemctl enable inland-api inland-celery-ai
sudo systemctl start inland-api inland-celery-ai

# 查看状态
sudo systemctl status inland-api
```

---

## 5. 数据库配置

### 5.1 PostgreSQL初始化

```bash
# 创建数据库和用户
sudo -u postgres psql

CREATE USER inland_user WITH PASSWORD 'your_secure_password';
CREATE DATABASE inland_shipping OWNER inland_user;
GRANT ALL PRIVILEGES ON DATABASE inland_shipping TO inland_user;
\q
```

### 5.2 PostgreSQL性能优化

编辑 `/etc/postgresql/15/main/postgresql.conf`：

```ini
# 内存配置（根据服务器内存调整）
shared_buffers = 2GB           # 总内存的25%
effective_cache_size = 6GB    # 总内存的75%
work_mem = 64MB
maintenance_work_mem = 256MB

# 连接配置
max_connections = 100

# 日志
log_min_duration_statement = 1000   # 记录超过1秒的SQL
```

### 5.3 数据库备份

```bash
# 每日自动备份（添加到crontab）
0 3 * * * /usr/bin/pg_dump -U inland_user inland_shipping | \
    gzip > /backup/inland_$(date +%Y%m%d).sql.gz

# 保留最近30天
0 4 * * * find /backup -name "inland_*.sql.gz" -mtime +30 -delete
```

---

## 6. Celery任务队列配置

### 6.1 Redis配置

编辑 `/etc/redis/redis.conf`：

```ini
# 绑定地址（仅本机访问）
bind 127.0.0.1

# 认证密码（必须设置）
requirepass your_redis_password

# 持久化（防止重启丢失任务）
appendonly yes
appendfsync everysec

# 最大内存限制
maxmemory 1gb
maxmemory-policy allkeys-lru
```

### 6.2 Celery监控（Flower）

```bash
# 安装Flower
pip install flower

# 启动Flower监控面板（端口5555）
celery -A app.tasks.celery_app flower \
    --port=5555 \
    --basic_auth=admin:your_flower_password

# 访问：http://your-domain:5555
```

> **建议：** 将Flower部署在内网，或通过Nginx添加访问控制。

### 6.3 队列说明

| 队列名 | 处理任务 | 推荐Worker数 |
|--------|---------|------------|
| `ai` | 货源文本AI解析 | 2-4个 |
| `analysis` | 统计数据聚合 | 1-2个 |
| `dispatch` | 货运调度匹配（V2） | 1个 |

---

## 7. Nginx反向代理配置

### 7.1 安装SSL证书

```bash
# 使用Let's Encrypt（免费）
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 7.2 Nginx配置

创建 `/etc/nginx/sites-available/inland-shipping`：

```nginx
# HTTP重定向到HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}

# HTTPS主配置
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL证书
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # SSL安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;

    # 安全Headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;

    # 日志
    access_log /var/log/nginx/inland_access.log;
    error_log /var/log/nginx/inland_error.log;

    # API代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时配置（AI解析可能较慢）
        proxy_connect_timeout 30s;
        proxy_read_timeout 120s;
        proxy_send_timeout 30s;

        # 限流（防止滥用）
        limit_req zone=api burst=20 nodelay;
    }

    # Swagger UI（可选：仅内网访问）
    location /docs {
        # allow 10.0.0.0/8;   # 限制内网访问
        # deny all;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /redoc {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    # 健康检查
    location /health {
        proxy_pass http://127.0.0.1:8000;
        access_log off;
    }
}

# 限流区域配置（在http块中）
# 在 /etc/nginx/nginx.conf 的 http 块中添加：
# limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/inland-shipping /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## 8. 环境变量说明

生产环境 `.env.production` 完整配置：

```env
# ─── 应用 ───────────────────────────────────────────
APP_NAME=中国内河航运数据采集与分析平台
APP_VERSION=2.0.0
DEBUG=false                              # 生产环境必须为false

# ─── 数据库 ─────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://inland_user:PASSWORD@localhost:5432/inland_shipping

# ─── 认证 ───────────────────────────────────────────
# 必须使用强随机密钥！使用以下命令生成：
# python3 -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=<64位随机字符串>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# ─── AI服务 ─────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx
AI_MODEL=claude-sonnet-4-6
AI_CONFIDENCE_THRESHOLD=60

# ─── Celery（生产必须配置） ──────────────────────────
CELERY_BROKER_URL=redis://:REDIS_PASSWORD@localhost:6379/0
CELERY_RESULT_BACKEND=redis://:REDIS_PASSWORD@localhost:6379/1

# ─── 定时任务 ───────────────────────────────────────
STATS_CRON_SCHEDULE=0 2 * * *          # 每日凌晨2点

# ─── CORS（生产环境指定实际域名） ──────────────────
ALLOWED_ORIGINS=["https://your-domain.com","https://www.your-domain.com"]
```

---

## 9. 数据库迁移

### 9.1 首次部署迁移

```bash
# Docker环境
docker compose exec api alembic upgrade head

# 裸机环境
source .venv/bin/activate
DATABASE_URL=postgresql+asyncpg://... alembic upgrade head
```

### 9.2 版本升级迁移流程

```bash
# 1. 拉取新代码
git pull origin main

# 2. 查看待执行迁移
alembic history --verbose
alembic current

# 3. 备份数据库（重要！）
pg_dump -U inland_user inland_shipping > backup_$(date +%Y%m%d_%H%M%S).sql

# 4. 执行迁移
alembic upgrade head

# 5. 验证
alembic current
```

### 9.3 迁移回滚

```bash
# 回滚最后一次迁移
alembic downgrade -1

# 回滚到指定版本
alembic downgrade <revision_id>
```

---

## 10. 监控与运维

### 10.1 日志收集

**应用日志位置：**

| 服务 | 日志路径 |
|------|---------|
| FastAPI | `/var/log/inland/access.log`, `error.log` |
| Nginx | `/var/log/nginx/inland_access.log` |
| Celery | `journalctl -u inland-celery-ai` |
| PostgreSQL | `/var/log/postgresql/` |

**日志轮转配置** `/etc/logrotate.d/inland`：

```
/var/log/inland/*.log {
    daily
    missingok
    rotate 30
    compress
    notifempty
    sharedscripts
    postrotate
        systemctl reload inland-api
    endscript
}
```

### 10.2 健康检查

```bash
# 应用健康
curl https://your-domain.com/health

# 数据库连接
docker compose exec db pg_isready -U inland_user

# Redis连接
docker compose exec redis redis-cli ping

# Celery Worker状态
docker compose exec celery-ai celery -A app.tasks.celery_app inspect ping
```

### 10.3 性能监控指标

**关键监控指标：**

| 指标 | 告警阈值 |
|------|---------|
| API响应时间（P95） | > 2秒 |
| API错误率（5xx） | > 1% |
| Celery队列深度（ai队列） | > 100条 |
| PostgreSQL连接数 | > 80个 |
| Redis内存使用率 | > 80% |
| CPU使用率 | > 85% |
| 磁盘使用率 | > 80% |

### 10.4 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 重启特定服务
docker compose restart api

# 进入应用容器
docker compose exec api bash

# 查看实时日志
docker compose logs -f api

# 查看Celery任务统计
docker compose exec celery-ai celery -A app.tasks.celery_app inspect stats

# 手动触发每日统计
docker compose exec api python3 -c "
import asyncio
from app.tasks.analysis_tasks import compute_daily_stats
print(asyncio.run(compute_daily_stats.__wrapped__()))
"
```

---

## 11. 安全加固

### 11.1 防火墙配置

```bash
# Ubuntu UFW
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### 11.2 关键安全检查清单

- [ ] `DEBUG=false` 在生产环境
- [ ] `SECRET_KEY` 使用64位随机字符串
- [ ] PostgreSQL密码强度 ≥ 16字符
- [ ] Redis设置了密码认证
- [ ] Nginx开启了HTTPS，HTTP跳转HTTPS
- [ ] Swagger UI限制了访问（仅内网或关闭）
- [ ] `.env.production` 不在Git仓库中
- [ ] 数据库端口（5432）不对外暴露
- [ ] Redis端口（6379）不对外暴露
- [ ] 定期备份数据库
- [ ] SSL证书自动续期已配置

### 11.3 定期安全更新

```bash
# 每周执行系统更新
sudo apt update && sudo apt upgrade -y

# 更新Python依赖（检查安全漏洞）
pip install pip-audit
pip-audit -r requirements.txt
```

---

## 12. 故障排查

### API服务不响应

```bash
# 检查服务状态
docker compose ps
systemctl status inland-api

# 查看最近错误日志
docker compose logs --tail=50 api
journalctl -u inland-api -n 50

# 检查端口是否监听
ss -tlnp | grep 8000
```

### 数据库连接失败

```bash
# 验证数据库连接
docker compose exec api python3 -c "
import asyncio
from app.core.database import AsyncSessionLocal
async def test():
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text
        result = await db.execute(text('SELECT 1'))
        print('DB连接正常:', result.scalar())
asyncio.run(test())
"
```

### AI解析卡在PARSING状态

```bash
# 查看是否有Worker在运行
docker compose exec celery-ai celery -A app.tasks.celery_app inspect active

# 手动重置卡住的消息
docker compose exec api python3 -c "
import asyncio
from app.tasks.ai_tasks import cleanup_stale_parsing
result = cleanup_stale_parsing()
print('重置数量:', result)
"
```

### Celery任务积压

```bash
# 查看队列深度
docker compose exec redis redis-cli llen celery

# 清空队列（谨慎使用！）
docker compose exec redis redis-cli del celery

# 增加Worker
docker compose up -d --scale celery-ai=4
```

### 磁盘空间不足

```bash
# 查看磁盘使用
df -h

# 清理Docker悬空资源
docker system prune -f

# 清理旧日志
find /var/log/inland -name "*.log.gz" -mtime +7 -delete

# 清理PostgreSQL日志
sudo find /var/log/postgresql -name "*.log" -mtime +7 -delete
```

---

*文档版本：V2.0 | 最后更新：2026-03-14*
