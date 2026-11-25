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
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
