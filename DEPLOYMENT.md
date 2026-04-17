# Deployment Information

## Public URL

> Deploy to Railway or Render using the steps below. Replace `<your-app>` with your actual subdomain.

```
https://day12assignment-production.up.railway.app/
```

## Platform

**Railway** (primary) | **Render** (alternative)

Both config files are included:
- `06-lab-complete/railway.toml`
- `06-lab-complete/render.yaml`

---

## Deploy Steps

### Option A — Railway (< 5 minutes)

```bash
# Install CLI
npm i -g @railway/cli

# Authenticate
railway login

# From the 06-lab-complete directory:
cd 06-lab-complete
railway init

# Set environment variables
railway variables set ENVIRONMENT=production
railway variables set AGENT_API_KEY=<your-strong-secret-key>
railway variables set JWT_SECRET=<your-strong-jwt-secret>
railway variables set DAILY_BUDGET_USD=5.0
railway variables set RATE_LIMIT_PER_MINUTE=10
railway variables set LOG_LEVEL=INFO

# Deploy
railway up

# Get public URL
railway domain
```

### Option B — Render (Blueprint)

1. Push this repo to GitHub (ensure it is public or Render has access).
2. Go to [render.com](https://render.com) → **New** → **Blueprint**.
3. Connect the GitHub repository; Render auto-reads `06-lab-complete/render.yaml`.
4. Set secrets in the dashboard: `AGENT_API_KEY`, `JWT_SECRET`.
5. Click **Deploy** → receive URL.

---

## Test Commands

### Health Check
```bash
curl https://<your-app>.railway.app/health
# Expected: {"status":"ok","version":"1.0.0","environment":"production","uptime_seconds":...}
```

### Readiness Check
```bash
curl https://<your-app>.railway.app/ready
# Expected: {"ready":true}
```

### Authentication Required (no key)
```bash
curl -X POST https://<your-app>.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: HTTP 401 {"detail":"Invalid or missing API key..."}
```

### API Test (with authentication)
```bash
curl -X POST https://<your-app>.railway.app/ask \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is cloud deployment?"}'
# Expected: HTTP 200 {"question":"...","answer":"...","model":"gpt-4o-mini","timestamp":"..."}
```

### Rate Limiting Test
```bash
for i in {1..15}; do
  curl -s -X POST https://<your-app>.railway.app/ask \
    -H "X-API-Key: YOUR_AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"question": "Test '$i'"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail',d.get('answer','?'))[:60])"
done
# First 10: answer text
# 11+: Rate limit exceeded: 10 req/min
```

### Metrics (protected)
```bash
curl https://<your-app>.railway.app/metrics \
  -H "X-API-Key: YOUR_AGENT_API_KEY"
# Expected: {"uptime_seconds":...,"total_requests":...,"daily_cost_usd":...}
```

---

## Environment Variables Set on Platform

| Variable | Description | Example |
|---|---|---|
| `ENVIRONMENT` | Runtime environment | `production` |
| `PORT` | Injected automatically by Railway/Render | `8000` |
| `AGENT_API_KEY` | API key for authentication | (secret) |
| `JWT_SECRET` | JWT signing secret | (secret) |
| `REDIS_URL` | Redis connection string | `redis://...` |
| `DAILY_BUDGET_USD` | Daily cost cap in USD | `5.0` |
| `RATE_LIMIT_PER_MINUTE` | Max requests per minute per user | `10` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `OPENAI_API_KEY` | Real LLM (optional; mock used if absent) | (secret) |

---

## Local Development

```bash
cd 06-lab-complete
cp .env.example .env
# Edit .env — set AGENT_API_KEY to any non-default value

docker compose up

# Test
curl http://localhost:8000/health
curl -H "X-API-Key: dev-key-change-me" \
     -X POST http://localhost:8000/ask \
     -H "Content-Type: application/json" \
     -d '{"question": "Hello from local!"}'
```

---

## Production Readiness Check

```bash
cd 06-lab-complete
python check_production_ready.py
# Result: 20/20 checks passed (100%) 🎉
```

---

## Screenshots

Place screenshots in a `screenshots/` folder:

- `screenshots/dashboard.png` — Railway/Render deployment dashboard
- `screenshots/running.png` — Service running (health check response)
- `screenshots/test.png` — Successful API test with authentication
