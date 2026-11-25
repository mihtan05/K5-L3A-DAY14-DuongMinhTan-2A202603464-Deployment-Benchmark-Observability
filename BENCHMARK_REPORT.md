# Benchmark & Observability Report — Day 14

**Họ tên:** Duong Minh Tan — 2A202603464
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 laptop, Python 3.12 (venv), Docker Desktop (Docker 29.7.2). Load test và agent chạy cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Ngưỡng mặc định của `load_test.py`; mock LLM trả lời ~200 ms nên 500 ms chừa chỗ cho retrieval + mạng, người dùng chat vẫn thấy nhanh. |
| Error rate `/ask` | < 2 % | Mock LLM có lỗi 503 ngẫu nhiên ~1%; 2% đủ chặt để bắt sự cố thật nhưng không báo động vì nhiễu bình thường. |
| Accuracy trên golden dataset | ≥ 80 % và 0 regression (bản cuối chạy với `--min-accuracy 1.0`) | Đúng quality gate mặc định của `run_eval.py`; bản fix KB nâng lên 100% để không chấp nhận câu nào sai. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.59 | 205.5 | 538.2 | 1711.9 | 1.00% | FAIL (p95) |
| 10 | 34.67 | 199.1 | 496.1 | 1715.4 | 2.67% | FAIL (error rate) |
| 50 | 92.44 | 223.1 | 551.6 | 1694.6 | 0.33% | FAIL (p95) |
| 100 | 40.3 | 1041.6 | 5293.8 | 5570.4 | 0.33% | FAIL (p95) |

Nguồn: `reports/load_v2_c{1,10,50,100}.json` (300 request mỗi mức).

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

Gần tuyến tính từ 1 → 10 (3.59 → 34.67, ×9.7) vì mỗi request chủ yếu *chờ* mock LLM (I/O async), một process xử lý song song được nhiều request. Từ 10 → 50 chỉ còn ×2.7 (92.44 RPS) và ở 100 RPS **giảm** còn 40.3 trong khi p50 tăng từ ~200 ms lên 1041.6 ms: agent chạy 1 process uvicorn, cùng máy với load generator, nên tới ngưỡng bão hoà request phải xếp hàng chờ event loop/CPU — thêm concurrency chỉ làm hàng đợi dài hơn chứ không tăng thông lượng. p99 ≈ 1.7 s ở mọi mức ≤ 50 là do ~3% request bị mock làm chậm (`MOCK_SLOW_RATE`), không phải do tải. Lỗi 2.67% ở c=10 là lỗi 503 ngẫu nhiên của mock (8/300), không phụ thuộc tải (c=50, c=100 chỉ 0.33%).

### 2.2 Tail latency

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 212.3 | 483.0 | 499.7 |
| 0.03 (mặc định) | 249.8 | 490.7 | 1720.2 |
| 0.1 | 349.5 | 1687.8 | 1743.4 |

Nguồn: `reports/load_v2_slow_{0,0.03,0.1}.json` (300 request, concurrency 20).

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

p99 nhạy nhất: chỉ 3% request chậm đã đẩy p99 từ 499.7 lên 1720.2 ms (×3.4) trong khi avg chỉ tăng 212.3 → 249.8 ms (+18%). Khi tỉ lệ chậm lên 10% (> 5%) thì tới lượt p95 nhảy 490.7 → 1687.8 ms. Average gộp số ít request rất chậm với số đông request nhanh nên trông vẫn "ổn" (349.5 ms ở 10% chậm) dù cứ 10 người dùng có 1 người chờ ~1.7 s. SLO theo p95/p99 đo đúng trải nghiệm của nhóm người dùng tệ nhất, nên bắt được tail latency mà average che mất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.7 | 108.8 | 115.1 |
| Tổng cost (USD) | 0.000399 | 0.000758 | 0.000803 |
| Cost / câu đúng (USD) | 0.00039915 | 0.00003607 | 0.00003492 |
| Quality gate | FAIL | PASS (≥ 80%, 0 regression) | PASS (≥ 100%, 0 regression so với v2) |

Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 | token, hết hạn, chữ ký | Thêm entry KB kích hoạt bởi `jwt` / `json web token`: JWT là token có chữ ký số và thời điểm hết hạn, khác API key cố định |
| scaling-03 | cpu, memory, custom metrics | Thêm entry KB kích hoạt bởi `hpa` / `autoscal` / `kubernetes`: HPA scale theo CPU, memory hoặc custom metrics |

Cả hai câu sai vì retrieval không tìm được tài liệu nào (agent rơi về câu trả lời chung chung). Sửa `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py` (đã chép sang `production/utils/mock_llm.py`), không sửa `golden_dataset.jsonl`.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

v2 tốn gấp ~1.9 lần token/câu (56.7 → 108.8) và tổng cost gấp ~1.9 lần (0.000399 → 0.000758 USD), p95 eval tăng 46 ms (200.9 → 246.9 ms) vì thêm bước retrieval và prompt dài hơn. Đổi lại accuracy từ 4.3% lên 91.3%, nên **cost / câu đúng giảm ~11 lần** (0.00039915 → 0.00003607). Vì vậy so hai phiên bản phải theo cost / câu đúng: v1 rẻ mỗi câu nhưng gần như mọi đồng tiêu đều cho câu trả lời sai. Bản fix KB tăng thêm ~6% token (prompt có thêm ngữ cảnh) nhưng cost / câu đúng còn giảm tiếp (0.00003492).

**Chặn merge bằng exit code (Exercise 7.3):** `run_eval.py` trả exit code ≠ 0 khi quality gate FAIL (accuracy dưới `--min-accuracy` hoặc có regression so với `--baseline`). Job CI `.github/workflows/eval-gate.yml` bật agent v2 rồi chạy `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline ../../../reports/eval_v2.json` (baseline v2 đã commit ở `reports/`); step fail → check của PR đỏ, đặt check này là *required* trong branch protection thì PR không merge được.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | pending +15 s, **firing ≈ 83 s** (`for: 1m`) | Error rate (Golden Signals) đỏ; Jaeger có trace lỗi với event `exception` |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | pending +15 s, **firing ≈ 143 s** (`for: 2m`) | p95/p99 theo thời gian vọt lên ~2 s, avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | Không đo được: alert **đã firing từ 08:28:32 UTC**, trước lúc đổi model, do tải 100 user của benchmark scale (cost > $2/giờ ngay cả với model small) | Cost USD/giờ, LLM p95 (model large chậm hơn) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` | **firing ≈ 45 s** sau khi pause (`for: 30s` + chu kỳ scrape/evaluate) | Instances up giảm 3 → 2; panel Error rate của agent không thấy lỗi 504 của Nginx |
| E | `AGENT_VERSION=v1` | | | |

Cách làm: giữ Locust 30 user chạy nền; lúc 08:32:30 UTC đổi `.env` thành `MOCK_ERROR_RATE=0.2`, `MOCK_SLOW_RATE=0.3`, `LLM_MODEL=mock-llm-large` rồi `docker compose -p k5-day14-observability up -d --scale agent=3`; 8 s sau (T0 = 08:32:38 UTC) `docker pause` agent-1. Một script poll `GET /api/v1/alerts` của Prometheus mỗi 5 s và ghi thời điểm đầu tiên mỗi alert chuyển trạng thái (so với T0; thời gian A, B trong bảng đã cộng 8 s từ lúc đổi `.env`):

```text
+   5.4s  AgentInstanceDown        pending
+   5.4s  LLMCostBurnRateHigh      firing   (activeAt 08:28:32Z — đã firing từ trước)
+  15.4s  AgentHighErrorRate       pending
+  15.4s  AgentHighLatencyP95      pending
+  45.5s  AgentInstanceDown        firing
+  75.5s  AgentHighErrorRate       firing
+ 135.6s  AgentHighLatencyP95      firing
```

Cả 4 alert cùng firing lúc chụp `screenshots/prometheus-alert-firing.png`. Thời gian tới lúc firing ≈ thời gian `for` của rule + tối đa một chu kỳ scrape/evaluate (15 s) + thời gian cửa sổ `rate()` tích đủ dữ liệu xấu.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `f31b343c0398efea97425ac1ac3d1141` (trong lúc chạy thí nghiệm B + C)
- Tổng thời gian: 2037.0 ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-large` (1982.1 ms, **97.3%**); `agent.retrieve_context` chỉ 52.6 ms

```text
POST /ask                      2037.0 ms   http.status_code=200
└── agent.run                  2035.0 ms
    ├── agent.retrieve_context   52.6 ms
    └── chat mock-llm-large    1982.1 ms   gen_ai.request.model=mock-llm-large
```

- Dòng log tương ứng (grep theo `trace_id`):

```json
{"ts": "2026-11-25T08:33:24.489899+00:00", "level": "INFO", "service": "observable-agent", "instance": "0a42cb75956b", "event": "http_request", "trace_id": "f31b343c0398efea97425ac1ac3d1141", "span_id": "a95d871ad80d0316", "request_id": "a58e4aa97119", "method": "POST", "route": "/ask", "status": 200, "ms": 2036.4}
```

Kết luận: request chậm vì LLM upstream, không phải code của agent.

**Trace lỗi** (`screenshots/jaeger-error-trace.png`): `trace_id` `100719846e0214a5f4dcc3bf3b1831d8`, `POST /ask` 211.9 ms trả 503; span `chat mock-llm-large` (190.4 ms) và `agent.run` có `error=true` và event `exception`. Dòng log:

```json
{"ts": "2026-11-25T08:35:07.972077+00:00", "level": "INFO", "service": "observable-agent", "instance": "92d457eb9516", "event": "llm_error", "trace_id": "100719846e0214a5f4dcc3bf3b1831d8", "span_id": "73e2c55f14198fab", "request_id": "95e68d09b787", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 58.47 | 200 | 840 | 1700 | 82 / 6940 (1.18%) |
| 3 | 60.28 | 200 | 270 | 1700 | 68 / 7174 (0.95%) |

Nguồn: hàng `POST,/ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv` (Locust headless, `-u 100 -r 10 -t 2m`). Hàng Aggregated (gồm cả `/health`): 64.01 và 65.91 req/s.

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- **p95 cải thiện rõ: 840 → 270 ms.** Với 1 instance (1 uvicorn worker), lúc tải cao request phải xếp hàng chờ nên p90/p95 phình ra (410/840 ms). 3 instance chia tải nên gần như không còn xếp hàng (p90 230 ms).
- **RPS gần như không đổi (58.47 → 60.28)** vì Locust là closed-loop: 100 user, mỗi user nghỉ `between(0.5, 2)` s giữa hai request, nên trần ≈ 100 / (1.25 s + ~0.25 s) ≈ 66 req/s. Aggregated đo được 64.01 và 65.91 req/s, tức là đã chạm trần của *load generator*, không phải của server. Muốn đo RPS tối đa phải tăng số user hoặc bỏ wait time.
- **p99 = 1700 ms ở cả hai lần** và median giữ nguyên 200 ms: đó là latency của chính LLM (khoảng 3% request bị mock làm chậm ~1.7 s, `MOCK_SLOW_RATE=0.03`). Thêm instance không làm LLM nhanh hơn, nên nút thắt của tail latency nằm ở LLM upstream (xem panel LLM latency), không phải ở số instance.
- Error rate ~1% ở cả hai lần là lỗi 503 ngẫu nhiên của mock (`MOCK_ERROR_RATE=0.01`), không do tải.

> Ghi chú: lần chạy đầu tiên 100% request lỗi 502 vì agent không khởi động được (`ModuleNotFoundError: uvicorn`). `production/Dockerfile` tạo user `agent` với HOME=`/app` nhưng copy gói `--user` vào `/home/agent/.local`. Tôi thêm `ENV PYTHONUSERBASE=/home/agent/.local`, build lại rồi chạy lại cả hai lần; CSV đã nộp là của lần chạy lại.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
