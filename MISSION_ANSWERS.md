# Day 14 Lab — Mission Answers

> Mọi output dưới đây lấy từ lệnh tôi chạy ngày 2026-11-25 (Windows 11, Docker Desktop, Docker 29.7.2). Token/key đã che.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret** — dòng 17–18: `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key và mật khẩu DB, phải revoke.
2. **Log lộ secret** — dòng 34: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Key xuất hiện trong log của platform (ai đọc log cũng thấy).
3. **`print()` thay vì logging có cấu trúc** — dòng 33, 38: không có level, timestamp, không lọc/tìm kiếm được trên hệ thống log.
4. **Config cứng trong code** — dòng 21–22: `DEBUG = True`, `MAX_TOKENS = 500`; đổi môi trường phải sửa code.
5. **Không có health check** — không có `/health` (gọi thử trả **404**), platform không biết agent chết để restart.
6. **Host/port cố định** — dòng 51–52: `host="localhost"` (không nhận kết nối từ ngoài container), `port=8000` (Railway/Render cấp `PORT` qua env).
7. **`reload=True`** — dòng 53: chế độ dev, tốn tài nguyên, không dùng cho production.
8. **Không xử lý shutdown** — không có lifespan/SIGTERM handler: request đang chạy có thể bị cắt khi platform tắt container.

### Exercise 1.2: Chạy bản develop

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -o /dev/null -w '%{http_code}' http://localhost:8000/health
404

# log server:
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this     ← secret lộ ra log
```

Chạy được, nhưng chưa production-ready: lộ secret, không health check, chỉ nghe `localhost`.

### Exercise 1.3: So sánh develop vs production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (dòng 17–22) | `config.py` đọc env var (`Settings`), có `.env.example` | Cùng một code chạy dev/staging/prod; secret không nằm trong git |
| Secret | Key thật trong code + in ra log | Đọc từ env, không log | Lộ key = mất tiền / bị tấn công; xoá file không xoá được khỏi lịch sử git |
| Health check | Không có (404) | `GET /health` (liveness) + `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform biết khi nào restart, load balancer biết khi nào ngừng gửi traffic |
| Logging | `print()` | `logging` + `json.dumps` (JSON có field cố định) | Tìm kiếm/lọc/aggregate được trên log platform, nối được với trace |
| Shutdown | Đột ngột | `lifespan` + `signal.signal(SIGTERM, ...)`, set `is_ready=False` rồi chờ request xong | Deploy/scale không làm rơi request đang chạy |
| Host / Port | `localhost:8000` cứng | `0.0.0.0` + `PORT` từ env | Container nhận được traffic từ ngoài; khớp port platform cấp |
| Reload | `reload=True` luôn | `reload=settings.debug` | Không chạy chế độ dev trong production |

---

## Part 2: Docker

### Exercise 2.1: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — bản full (có compiler, công cụ build) nên rất nặng.
2. **Working directory:** `/app`.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo layer. Dependencies ít thay đổi hơn code, nên copy và `pip install` trước → sửa code chỉ build lại layer `COPY app.py`, không cài lại thư viện. Nếu `COPY . .` trước thì mọi thay đổi code đều làm mất cache bước `pip install`.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số mặc định, bị ghi đè hoàn toàn khi `docker run image <lệnh khác>`. `ENTRYPOINT` là executable cố định, tham số của `docker run` được nối vào sau nó (muốn đổi phải `--entrypoint`). Hay dùng `ENTRYPOINT` cho executable + `CMD` cho tham số mặc định.

### Exercise 2.2: Build và chạy bản develop

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
HTTP/1.1 200 OK
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (builder, `python:3.11-slim`):** cài `gcc`, `libpq-dev`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này không được deploy.
- **Stage 2 (runtime, `python:3.11-slim`):** chỉ copy `/root/.local` (thư viện đã cài) + `main.py` + `utils/`, tạo user non-root `appuser`, có `HEALTHCHECK`.
- **Vì sao nhỏ hơn:** base `slim` thay cho bản full; compiler, header, apt cache, pip cache ở lại stage builder và bị bỏ đi.

Đo bằng `docker images my-agent`:

```text
my-agent:advanced  240MB
my-agent:develop   1.67GB
```

- Develop: **1.67 GB** (≈ 1670 MB)
- Production (advanced): **240 MB**
- Chênh lệch: (1670 − 240) / 1670 ≈ **85.6% nhỏ hơn**

### Exercise 2.4: Docker Compose stack (`02-docker/production/`)

```text
                ┌──────────────────────────┐
  client ──:80──▶  nginx (reverse proxy/LB)│
                └────────────┬─────────────┘
                             │ http://agent:8000   (network "internal")
                     ┌───────▼────────┐
                     │ agent (FastAPI)│
                     └───┬────────┬───┘
       redis://redis:6379│        │http://qdrant:6333
                ┌────────▼──┐  ┌──▼──────────┐
                │ redis      │  │ qdrant      │
                │ (cache,    │  │ (vector DB) │
                │ rate limit)│  └─────────────┘
                └────────────┘
```

Chạy `docker compose -p k5-day14-docker up -d --build` (đã `touch .env.local`): 4 service được start — `redis`, `qdrant` (healthy trước), rồi `agent` (`depends_on: condition: service_healthy`), rồi `nginx`. Chỉ nginx publish cổng 80/443; agent, redis, qdrant chỉ nằm trong network `internal` và gọi nhau bằng tên service (DNS nội bộ của Docker).

```text
$ curl -i http://localhost/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.6,"version":"2.0.0","timestamp":"2026-11-25T08:11:12.130367"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1: Railway (deploy agent Part 6)

- URL: _(điền sau khi deploy — xem `DEPLOYMENT.md`)_
- Screenshot: `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`

### So sánh `railway.toml` và `render.yaml` (trong `06-lab-complete/`)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng / phạm vi | TOML, cấu hình **một service** (build + deploy) | YAML Blueprint, khai báo **nhiều service** cùng lúc (web + Redis Key Value) |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `dockerfilePath`, thêm `rootDir: 06-lab-complete` vì Render đọc Blueprint ở gốc repo |
| Health check | `healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"` | Render tự quản lý, không cấu hình trong file |
| Biến môi trường / secret | Không có trong file: đặt bằng `railway variables` hoặc dashboard | Khai báo trong file: giá trị thường ghi thẳng, secret dùng `sync: false` (nhập tay trên dashboard), `REDIS_URL` lấy bằng `fromService` từ service Key Value |
| Redis | Thêm Redis service riêng trên Railway, `REDIS_URL` tham chiếu biến của nó | Khai báo luôn `type: keyvalue` trong Blueprint |
| PORT | Railway cấp `PORT`, Dockerfile đọc `${PORT:-8000}` | Render cũng cấp `PORT`, cùng Dockerfile dùng được |

Lý do khác nhau: Railway coi file chỉ là cấu hình build/deploy của một service, phần hạ tầng và secret quản lý ở dashboard/CLI; Render theo hướng Infrastructure-as-Code nên Blueprint mô tả cả hạ tầng (DB, Redis) và danh sách biến, chỉ để trống giá trị secret.

### Exercise 3.3: Pipeline CI/CD Cloud Run (`03-cloud-deployment/production-cloud-run/`)

1. **test:** `cloudbuild.yaml` chạy `pytest` trong `python:3.11-slim`; test fail thì dừng pipeline.
2. **build:** `docker build` image, gắn tag `$COMMIT_SHA` và `latest`, dùng `--cache-from` image `latest` để tận dụng layer cache.
3. **push:** đẩy mọi tag lên Container Registry `gcr.io/$PROJECT_ID/ai-agent`.
4. **deploy:** `gcloud run deploy` image theo `$COMMIT_SHA` lên region `asia-southeast1`, min 1 / max 10 instance, 512Mi / 1 CPU, `ENVIRONMENT=production`, secret `OPENAI_API_KEY` lấy từ Secret Manager.
5. `service.yaml` mô tả cùng service theo kiểu khai báo (Knative): `minScale 1` (tránh cold start), `maxScale 10`, `containerConcurrency: 80`, requests/limits CPU–RAM, secret qua `secretKeyRef`, `livenessProbe` + `startupProbe` gọi health endpoint.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop`, chạy với `AGENT_API_KEY=secret-key-123`)

- **Check ở đâu:** dependency `verify_api_key` dùng `APIKeyHeader(name="X-API-Key")`, gắn vào `/ask`.
- **Sai key:** thiếu key → **401**, có key nhưng sai → **403** (bản Part 6 của tôi trả 401 cho cả hai theo yêu cầu bài).
- **Rotate key:** key đọc từ env `AGENT_API_KEY` → đổi giá trị biến trên platform rồi restart/redeploy, không sửa code. Muốn không downtime thì cho phép tạm thời 2 key (cũ + mới) trong lúc client chuyển.

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong" ...
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

Flow: `POST /auth/token` với username/password → server kiểm tra (`authenticate_user`), ký JWT (HS256) chứa `sub`, `role`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token` kiểm chữ ký và hạn; hết hạn → 401, chữ ký sai → 403.

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN>"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":2.1e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window log — mỗi user một `deque` timestamp, bỏ các timestamp cũ hơn 60 s, đủ `max_requests` thì chặn.
- **Giới hạn:** user 10 req/phút (`rate_limiter_user`), admin 100 req/phút (`rate_limiter_admin`).
- **Bypass cho admin:** `app.py` chọn limiter theo `role` trong JWT: `limiter = rate_limiter_admin if role == "admin" else rate_limiter_user` — admin không bị bỏ giới hạn hẳn mà có limit cao hơn.

Vòng lặp với cùng token (request "with token" ở trên là request thứ 1 trong cửa sổ):

```text
#1..#9  HTTP/1.1 200 OK
#10     HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard

Bản mẫu (`04-api-gateway/production/cost_guard.py`) lưu chi phí trong RAM theo user/ngày: `check_budget` trước khi gọi LLM (user vượt $1/ngày → **402**, tổng hệ thống vượt $10/ngày → 503), `record_usage` sau khi gọi LLM tính `input_tokens × giá input + output_tokens × giá output`.

Cách tôi làm trong Part 6 (`06-lab-complete/app/cost_guard.py`), state nằm trong **Redis** để mọi instance dùng chung:

```python
def check_budget():                       # TRƯỚC khi gọi LLM
    spent = float(r.get("cost:" + today) or 0)
    if spent >= settings.daily_budget_usd:
        raise HTTPException(402, "Daily budget exceeded")

def record_cost(input_tokens, output_tokens):   # SAU khi gọi LLM
    cost = input_tokens/1000*0.00015 + output_tokens/1000*0.0006
    r.incrbyfloat("cost:" + today, cost)  # atomic, an toàn khi nhiều worker
    r.expire("cost:" + today, 2*24*3600)  # key theo ngày → tự "reset" khi sang ngày mới
```

Rate limit bảo vệ **tốc độ** (chống spam/DoS trong một phút), cost guard bảo vệ **tiền** (tổng chi phí cả ngày/tháng). Cần cả hai: một user gửi chậm, đều dưới rate limit, với prompt rất dài vẫn có thể đốt hết ngân sách.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health vs readiness

- `GET /health` (**liveness**): process còn sống → 200. Fail → platform **restart** container. Không được phụ thuộc Redis/DB, nếu không Redis chết sẽ kéo theo restart hàng loạt vô ích.
- `GET /ready` (**readiness**): đủ điều kiện nhận traffic (startup xong, Redis kết nối được) → 200, ngược lại 503. Fail → load balancer **ngừng gửi traffic** tới instance đó nhưng không restart.

Trong Part 6: `/health` luôn 200; `/ready` ping Redis, mất Redis → 503 (script chấm đã kiểm cả hai trường hợp).

### Exercise 5.2: Graceful shutdown

`05-scaling-reliability/develop/app.py` đếm `_in_flight_requests` bằng middleware; khi shutdown đặt `_is_ready = False` (`/ready` trả 503 → LB ngừng gửi request mới) rồi chờ tới khi `_in_flight_requests == 0` (có timeout) mới thoát.
Trong Part 6 tôi dựa vào uvicorn: nhận SIGTERM → ngừng accept kết nối mới, chờ request đang chạy xong, chạy phần shutdown của `lifespan`, exit code 0. Không tự đăng ký handler SIGTERM (nếu có thì phải gọi lại handler của uvicorn). Kết quả kiểm tra: gửi SIGTERM khi đang có request → request vẫn 200, exit code 0; `docker stop` → exit code 0, < 10 s.

### Exercise 5.3: Stateless

State trong RAM (`conversation_history = {}`) chỉ tồn tại trong một process: chạy 3 instance sau load balancer thì mỗi request có thể rơi vào instance khác và không thấy history; restart/scale down là mất dữ liệu. `05-scaling-reliability/production/app.py` lưu session trong Redis (`session:{id}` với `setex` TTL), mọi instance đọc chung.

### Exercise 5.4 + 5.5: Load balancing + test stateless

```text
$ docker compose -p k5-day14-scaling up -d --build --scale agent=3
k5-day14-scaling-agent-1   Up (healthy)
k5-day14-scaling-agent-2   Up (healthy)
k5-day14-scaling-agent-3   Up (healthy)
k5-day14-scaling-nginx-1   Up
k5-day14-scaling-redis-1   Up (healthy)

$ python test_stateless.py
Request 1: [instance-92c65d]  Q: What is Docker?
Request 2: [instance-9e2132]  Q: Why do we need containers?
Request 3: [instance-92c65d]  Q: What is Kubernetes?
Request 4: [instance-b23c9e]  Q: How does load balancing work?
Request 5: [instance-9e2132]  Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-9e2132', 'instance-92c65d', 'instance-b23c9e'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** Nginx (cổng 8080) chia 5 request của cùng một session cho cả 3 instance theo round-robin. Dù vậy history đọc về đủ 10 message (5 user + 5 assistant) theo đúng thứ tự, vì không instance nào giữ state trong RAM: mỗi request đọc session từ Redis, append rồi ghi lại. Nếu history nằm trong RAM, mỗi instance chỉ thấy phần của nó (2, 2, 1 câu). Script không tắt instance nào; vì state ở Redis, tắt một instance thì 2 instance còn lại vẫn phục vụ tiếp session đó.

---

## Part 6: Final Project — output `check_production_ready.py`

_(sẽ dán output `PASS 12/12` chạy trong WSL2 — xem ghi chú bên dưới)_

Lần chạy trên Windows (Docker có bật) — 11/12, 42/42 checks đạt; tiêu chí 11 ⚠️ chỉ vì Windows không gửi được SIGTERM (phần `docker stop` của tiêu chí 11 đã ✅):

```text
  📋 Checklist Deliverable
     ⚠️  Graceful shutdown
----------------------------------------------------------------
  Result: 11/12 tiêu chí đạt · 42/42 checks passed
```

---

## AI log

| # | Hỏi AI (Claude Code) gì | Nhận được gì | Tôi tự sửa / kiểm tra thế nào |
|---|---|---|---|
| 1 | Lập kế hoạch làm lab theo README/RUBRIC/CHECKPOINTS | Kế hoạch 6 bước theo CP, chỉ ra tên repo sai mẫu | Đối chiếu lại với RUBRIC và SUBMISSION |
| 2 | Viết các TODO Part 6 (`config`, `auth`, `rate_limiter`, `cost_guard`, `redis_client`, `main`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Code hoàn chỉnh dựa trên mẫu Part 4/5 | Chạy `check_production_ready.py` (static → full); chạy thêm trong container Linux để kiểm SIGTERM |
| 3 | Chạy load test, eval, sửa `KNOWLEDGE_BASE` cho 2 câu sai | Số đo trong `reports/*.json`, thêm 2 entry KB (JWT, HPA) | Eval cuối 23/23 PASS; số trong `BENCHMARK_REPORT.md` trích thẳng từ JSON |
| 4 | Chạy ví dụ Part 1, 2, 4, 5 và soạn câu trả lời | Output lệnh + bản nháp câu trả lời | Đọc lại code nguồn từng Part, kiểm từng dòng code được trích |
