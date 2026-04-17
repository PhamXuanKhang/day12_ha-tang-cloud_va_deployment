# Day 12 Lab — Mission Answers

> **Student Name:** Phạm Xuân Khang
> **Student ID:** 2A202600275
> **Date:** 2026-04-17

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found in `01-localhost-vs-production/develop/app.py`

1. **Hardcoded API key** — `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` — pushing to GitHub exposes the secret immediately.
2. **Hardcoded database URL with credentials** — `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"` — same risk as above.
3. **Logging secrets** — `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` — secrets end up in log aggregators.
4. **`print()` instead of structured logging** — no log level, no timestamps, unstructured text; impossible to parse in production log systems.
5. **No health check endpoint** — the platform has no way to detect or restart a crashed/frozen container.
6. **Fixed `host="localhost"`** — a container listening on `localhost` only accepts traffic from itself; external traffic is silently dropped.
7. **Fixed `port=8000`** — cloud platforms (Railway, Render) inject `PORT` via env var; ignoring it makes the app unreachable.
8. **`reload=True` in production** — debug reload consumes extra resources and can expose file-system details.
9. **No graceful shutdown** — `SIGTERM` from the orchestrator kills the process mid-request; no cleanup of connections.
10. **No input validation** — `question: str` query param with no length limit or sanitisation; potential for abuse/injection.

---

### Exercise 1.3: Comparison table — Basic vs Production

| Feature | Basic (`develop/`) | Production (`production/`) | Why Important? |
|---|---|---|---|
| **Config** | Hardcoded strings | `os.getenv()` via `config.py` (12-Factor) | Secrets stay out of code; one build works in every environment |
| **Health check** | Missing | `GET /health` + `GET /ready` | Platform can auto-restart unhealthy containers |
| **Logging** | `print()` + secrets logged | Structured JSON, no secrets | Machine-parseable; compatible with Datadog/Loki/CloudWatch |
| **Shutdown** | Abrupt (no handler) | `signal.SIGTERM` + lifespan cleanup | In-flight requests complete before process exits |
| **Host binding** | `localhost` | `0.0.0.0` | Container can receive traffic from outside |
| **Port** | Hard-coded `8000` | `int(os.getenv("PORT", "8000"))` | Cloud platforms inject the port; app must listen on it |
| **Debug mode** | Always `reload=True` | `reload` only when `DEBUG=true` | Avoids resource waste and information leakage |
| **CORS** | None | Configured via `ALLOWED_ORIGINS` env var | Restricts cross-origin access to known clients |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` — full Python distribution (~1 GB).
2. **Working directory:** `/app`
3. **Why copy `requirements.txt` first?** Docker caches each layer. If only `app.py` changes, the layer with installed packages is still cached — avoiding a full `pip install` on every build.
4. **CMD vs ENTRYPOINT:**
   - `ENTRYPOINT` sets the fixed executable; arguments can be appended at `docker run` time.
   - `CMD` provides default arguments that are *replaced* entirely if anything is passed to `docker run`.
   - Using `CMD ["python", "app.py"]` allows easy override (e.g., `docker run img python shell.py`).

---

### Exercise 2.3: Multi-stage build (`02-docker/production/Dockerfile`)

**Stage 1 (builder):** Uses `python:3.11-slim` + `gcc`/`libpq-dev` to compile native extensions and installs all packages into `/root/.local` with `--user`.

**Stage 2 (runtime):** Starts from a clean `python:3.11-slim` — no build tools, no compiler. Only the pre-built packages are copied from the builder stage with `COPY --from=builder`.

**Why smaller?** The build tools (`gcc`, `libpq-dev`, package caches) never enter the final image. Only the compiled `.so` files and Python wheels are copied over.

**Image size comparison** (approximate):

| Image | Size | Notes |
|---|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | ~1.1 GB | Full Python + OS packages |
| `my-agent:production` (multi-stage, `python:3.11-slim`) | ~220 MB | Slim base + compiled deps only |
| **Difference** | ~80% smaller | Multi-stage eliminates build toolchain |

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway deployment

**Platform:** Railway

**Deployment steps:**
```bash
cd 03-cloud-deployment/railway
npm i -g @railway/cli
railway login
railway init
railway variables set PORT=8000
railway variables set AGENT_API_KEY=my-secret-key-123
railway up
railway domain   # returns public URL
```

**Health check test:**
```bash
curl https://<your-app>.railway.app/health
# {"status":"ok","uptime_seconds":...,"platform":"Railway","timestamp":"..."}
```

**Agent endpoint test:**
```bash
curl -X POST https://<your-app>.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is Docker?"}'
```

---

### Exercise 3.2: Render vs Railway config comparison

| Aspect | `railway.toml` | `render.yaml` |
|---|---|---|
| Build method | `builder = "DOCKERFILE"` | `runtime: docker` |
| Start command | Explicit `startCommand` field | Derived from Dockerfile `CMD` |
| Health check | `healthcheckPath` field | `healthCheckPath` field |
| Auto-generate secrets | Not supported | `generateValue: true` per env var |
| Region selection | Not in toml (set in dashboard) | `region: singapore` in YAML |
| Restart policy | `restartPolicyType = "ON_FAILURE"` | Platform default |

Key difference: Render's Blueprint YAML is more declarative (includes env vars, regions, auto-generated secrets); Railway's TOML focuses on build/deploy commands with secrets managed separately via CLI or dashboard.

---

## Part 4: API Security

### Exercise 4.1: API Key authentication (`04-api-gateway/develop/app.py`)

- **Where is the key checked?** In the `verify_api_key` dependency via `X-API-Key` request header, compared against `AGENT_API_KEY` env var.
- **Wrong key response:** `HTTP 401 Unauthorized` with detail `"Invalid or missing API key"`.
- **How to rotate?** Update `AGENT_API_KEY` env var on the platform (Railway/Render) and redeploy; no code change needed.

**Test results:**
```bash
# Without key → 401
curl http://localhost:8000/ask -X POST \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# {"detail":"Invalid or missing API key. Include header: X-API-Key: <key>"}

# With correct key → 200
curl http://localhost:8000/ask -X POST \
  -H "X-API-Key: secret-key-123" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# {"question":"Hello","answer":"...","model":"gpt-4o-mini","timestamp":"..."}
```

---

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

**JWT flow:**
1. `POST /auth/token` with `{"username": "student", "password": "demo123"}` → server issues signed JWT (HS256, 60-min expiry).
2. Client includes `Authorization: Bearer <token>` in subsequent requests.
3. Server decodes and verifies signature on every request — **no database lookup needed** (stateless).
4. If token is expired → `401 Token expired`; if signature invalid → `403 Invalid token`.

**Test:**
```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"student","password":"demo123"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use token
curl http://localhost:8000/ask -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "Explain JWT"}'
```

---

### Exercise 4.3: Rate limiting (`04-api-gateway/production/rate_limiter.py`)

- **Algorithm:** Sliding Window Counter — timestamps of each request are stored in a `deque`; timestamps older than `window_seconds` are evicted before each check.
- **Limit:** `rate_limiter_user = RateLimiter(max_requests=10, window_seconds=60)` → 10 requests per minute for regular users; admins get 100/min.
- **Admin bypass:** Role-based limiter selection — `rate_limiter_admin` is used when `user["role"] == "admin"`.

**Test (hitting the limit):**
```bash
for i in {1..15}; do
  curl -s http://localhost:8000/ask -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"question": "Test '$i'"}' | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','ok'))"
done
# First 10: ok
# 11+: {"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":...}
```

---

### Exercise 4.4: Cost guard implementation

**Approach:** In-memory daily budget per user + global daily cap.

**Logic (from `04-api-gateway/production/cost_guard.py` and `06-lab-complete/app/cost_guard.py`):**

```python
def check_budget(user_id: str) -> None:
    # 1. Reset global cost counter if day changed
    # 2. Check global daily cap (503 if exceeded)
    # 3. Get or create today's UsageRecord for this user
    # 4. Calculate cost from token counts at pricing rates
    # 5. Raise HTTP 402 if user has exceeded their daily budget
    # 6. Log a warning at 80% usage
```

- Token pricing: GPT-4o-mini rates — $0.00015/1K input, $0.0006/1K output
- Budget: `DAILY_BUDGET_USD=5.0` (configurable via env var)
- Reset: Automatic daily reset via date comparison (`time.strftime("%Y-%m-%d")`)
- **Redis variant** (production-grade): Uses `r.incrbyfloat(key, cost)` with TTL of 32 days; key pattern `budget:{user_id}:{YYYY-MM}` for monthly budgets that survive restarts and scale across instances.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

Two separate probes serve different purposes:

```python
@app.get("/health")   # Liveness — "Is the process alive?"
def health():
    return {"status": "ok", "uptime_seconds": ..., "version": ...}
    # Always 200 if the process can respond at all; triggers container restart if unreachable

@app.get("/ready")    # Readiness — "Can this instance serve traffic?"
def ready():
    if not _is_ready:  # set True after startup initialisation completes
        raise HTTPException(503, "Not ready")
    return {"ready": True}
    # Load balancer stops routing here during startup/shutdown
```

---

### Exercise 5.2: Graceful shutdown

```python
import signal

def _handle_signal(signum, _frame):
    logger.info(json.dumps({"event": "signal", "signum": signum}))
    # uvicorn's timeout_graceful_shutdown=30 drains in-flight requests

signal.signal(signal.SIGTERM, _handle_signal)
# uvicorn is started with: timeout_graceful_shutdown=30
```

**Behaviour observed:**
- Send `kill -TERM <PID>` → handler logs the signal; uvicorn waits up to 30 s for in-flight requests to complete before exiting.
- Without handler: process exits immediately, potentially mid-response.

---

### Exercise 5.3: Stateless design

**Anti-pattern (breaks at scale):**
```python
conversation_history = {}  # lives in one instance's memory

@app.post("/ask")
def ask(user_id: str, question: str):
    history = conversation_history.get(user_id, [])  # other instances have no data!
```

**Correct (Redis-backed, from `05-scaling-reliability/production/app.py`):**
```python
@app.post("/chat")
async def chat(body: ChatRequest):
    session_id = body.session_id or str(uuid.uuid4())
    append_to_history(session_id, "user", body.question)  # writes to Redis
    session = load_session(session_id)                     # reads from Redis
    answer = ask(body.question)
    append_to_history(session_id, "assistant", answer)
    return {..., "served_by": INSTANCE_ID}  # any instance can serve any user
```

**Why Redis?** All instances share one Redis; any instance can read any session. Conversations survive instance restarts. State can be inspected/debugged externally.

---

### Exercise 5.4: Load balancing

**Starting 3 instances:**
```bash
docker compose up --scale agent=3
```

Nginx (`nginx.conf`) uses `upstream agent { server agent:8000; }` — Docker's internal DNS load-balances across all three containers with the same service name.

**Test (seeing distribution):**
```bash
for i in {1..10}; do
  curl -s http://localhost/ask -X POST \
    -H "Content-Type: application/json" \
    -d '{"question": "Request '$i'"}' | python -c "import sys,json; print(json.load(sys.stdin).get('served_by','?'))"
done
# instance-abc123
# instance-def456
# instance-abc123
# ...  ← requests distributed across 3 instances
```

If one instance is killed, Nginx's health checks route remaining traffic to the two surviving instances.

---

### Exercise 5.5: Stateless test

```bash
cd 05-scaling-reliability/production
python test_stateless.py
```

The script:
1. Creates a conversation via `POST /chat` → receives `session_id`
2. Sends a follow-up message on the same `session_id`
3. Verifies that the conversation history is preserved even when the request lands on a different instance
4. Expected result: `✅ Conversation history preserved across instances` — proof of stateless design.

---

## Part 6: Final Project Summary

The complete production agent is in `06-lab-complete/`. It combines all concepts:

| Requirement | Implementation |
|---|---|
| Multi-stage Dockerfile | `06-lab-complete/Dockerfile` — builder + runtime stages, non-root user, `HEALTHCHECK` |
| Config from env vars | `app/config.py` — `@dataclass` with `os.getenv()` for every setting |
| API key auth | `app/auth.py` + `app/main.py` — `X-API-Key` header, `verify_api_key` dependency |
| Rate limiting (10 req/min) | `app/rate_limiter.py` — sliding window counter, `HTTP 429` with `Retry-After` header |
| Cost guard ($5/day) | `app/cost_guard.py` — per-user daily budget, global cap, `HTTP 402` when exceeded |
| Health + readiness checks | `GET /health` (liveness) + `GET /ready` (readiness) |
| Graceful shutdown | `signal.SIGTERM` handler + `uvicorn timeout_graceful_shutdown=30` |
| Stateless design | State in Redis (`REDIS_URL`); in-memory fallback for dev |
| No hardcoded secrets | All secrets via env vars; `check_production_ready.py` validates this |
| Public deployment | `railway.toml` + `render.yaml` included; see `DEPLOYMENT.md` |

**Validation result:**
```
python 06-lab-complete/check_production_ready.py
# Result: 20/20 checks passed (100%)
# 🎉 PRODUCTION READY!
```
