---
name: deploy
description: Push current branch to git, then SSH into Tencent Cloud and restart docker-compose. Confirms with user before any push or SSH.
argument-hint: "[commit-message]"
model: sonnet
allowed-tools:
  - Bash
  - Read
---

# Deploy to Tencent Prod

Deploys the current branch to the Tencent Cloud Ubuntu host running this app under docker-compose.

## ⚠️ Confirmation required

This skill PUSHES code AND restarts production. Confirm with user before each network step.

## Step 1 — Check git state

```bash
git status --short
git log -1 --oneline
```

If working tree is dirty:
- If user provided `$1` (commit message): `git add -A && git commit -m "$1"`
- Otherwise: STOP and ask user how to handle uncommitted changes.

## Step 2 — Push (ASK FIRST)

Ask: "Push current branch to origin? (y/n)"

On confirm:
```bash
git push
```

## Step 3 — SSH and 智能 deploy (ASK FIRST)

Ask: "SSH to tencent-prod and deploy? (y/n)"

⚠️ **2026-05-09 OOM 事故教训**: prod 直接 `docker compose up -d --build` 会撑死 4G VPS
(build 进程逃出 mem_limit 约束, chromium 解压峰值 1-2GB → OOM thrashing → 强制重启).

新流程：**仅 Dockerfile / requirements / playwright 改动时才 build, 否则 restart**.
这样 deploy templates / static / 纯 Python 改动时 0 build 风险.

On confirm:
```bash
ssh tencent-prod << 'REMOTE'
  set -e
  cd /root/clean-industry-ai-assistant
  git pull
  if git diff HEAD@{1} HEAD --name-only | grep -qE '^(Dockerfile|requirements.*\.txt|playwright)'; then
    echo '[deploy] 检测 Dockerfile/requirements 改动 → 必须 build (注意 OOM 风险)'
    echo '[deploy] 如果机器内存仍是 4G, 强烈建议先做 PR-B (镜像仓库 pull) 或升级硬件'
    docker compose up -d --build
  else
    echo '[deploy] 仅 app/templates/static 改动 → restart 即可 (零 OOM 风险)'
    docker compose restart web
  fi
  sleep 5
  docker compose ps
REMOTE
```

Expected: container shows `Up X (healthy)`. `Restarting` / `Exit` / `(unhealthy)` = fail.

## Step 4 — Health check

```bash
ssh tencent-prod "curl -s http://localhost:5000/ -o /dev/null -w '%{http_code}'"
ssh tencent-prod "docker compose logs --tail=30 web"
```

Expected: HTTP 200 + no traceback in logs.

## Step 5 — Report

```
[deploy] OK
- branch: main
- commit: <sha> <message>
- container: up
- health: 200
- logs: clean
```

Any failure → report the failed step + relevant log excerpt + STOP.
