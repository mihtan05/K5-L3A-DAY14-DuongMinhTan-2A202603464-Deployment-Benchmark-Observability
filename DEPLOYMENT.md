# Deployment Information

## Public URL

https://agent-production-0fad661a.up.railway.app

## Platform

Railway — project `day14-agent`, environment `production`, gồm 2 service:

| Service | Nguồn | Ghi chú |
|---|---|---|
| `agent` | `railway up` từ thư mục `06-lab-complete/` (build bằng `Dockerfile` theo `railway.toml`) | Healthcheck `GET /health`, Railway cấp biến `PORT` |
| `Redis` | Railway Redis database | Chỉ truy cập qua mạng nội bộ `redis.railway.internal:6379` |

Deploy:

```bash
cd 06-lab-complete
railway init --name day14-agent
railway add --database redis
railway add --service agent --variables "AGENT_API_KEY=<random>" --variables 'REDIS_URL=${{Redis.REDIS_URL}}' ...
railway up --service agent --ci
railway domain --service agent
```

## Environment Variables (đặt trên Railway, không ghi trong code)

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | chuỗi ngẫu nhiên 32 ký tự hex — chỉ lưu trên Railway (xem bằng `railway variable list -s agent`) |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` — tham chiếu tới service Redis |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Railway tự cấp; `Dockerfile` đọc `${PORT:-8000}` |

## Test Commands

```bash
export BASE=https://agent-production-0fad661a.up.railway.app
export AGENT_API_KEY=<key trên Railway>

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả chạy lúc 2026-11-25 09:23 UTC (`screenshots/test.png`):

```text
200
200
401
200
$ curl -sS -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"What is deployment?"}'
{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","cost_usd":2.01e-05}
```

Rate limit trên cloud (cùng một key, 12 request liên tiếp, `RATE_LIMIT_PER_MINUTE=10`):

```text
200 200 200 200 200 200 200 200 429 429 429 429
```

(Hai request `/ask` có key trước đó trong cùng 60 giây cũng được tính, nên request thứ 9 của vòng lặp là request thứ 11 → 429.)

`python check_production_ready.py --static-only --public-url https://agent-production-0fad661a.up.railway.app`:

```text
✅ 12. Public URL ready (Railway / Render config)
     ✅ Public URL: GET https://agent-production-0fad661a.up.railway.app/health → 200
```

## Screenshots

- `screenshots/dashboard.png` — project `day14-agent` qua Railway CLI (`railway status`, `railway service list`): service `agent` và `Redis` đều ● Online; danh sách **tên** biến môi trường đặt trên Railway (không in giá trị)
- `screenshots/running.png` — deployment của `agent` trạng thái SUCCESS, log runtime trên Railway (request `/health`, `/ready`, `/ask` 401/200) và `curl` `/health`, `/ready` trả 200 lúc 09:48 UTC
- `screenshots/test.png` — kết quả 4 lệnh test ở trên

> `dashboard.png` và `running.png` chụp output của Railway CLI (đăng nhập bằng tài khoản của tôi, dữ liệu lấy từ Railway API), không phải giao diện web; tên tài khoản đã được che.
