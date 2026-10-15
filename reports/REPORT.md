# Day27 — báo cáo triển khai và kiểm chứng

**Họ tên:** Trần Quốc Vượng · **MSV:** 2A202602522

**Ngày thực hiện:** 15/10/2026 (Asia/Bangkok)

Repo public đã chuẩn hoá tên thành [K4-DAY27-TranQuocVuong-2A202602522](https://github.com/Neon310304/K4-DAY27-TranQuocVuong-2A202602522). [Setup](../docs/SETUP.md) và [setup.json](evidence/setup.json) ghi kiểm tra môi trường mới cùng khác biệt credential: YesScale qua OpenAI-compatible API, GitHub Credential Manager thay PAT classic `public_repo` riêng.

## Kết quả

Hoàn thiện năm bài tập, UI Streamlit, routing, HITL, escalation và audit SQLite. Bộ **30 tests offline đạt**. **8 kiểm tra trình duyệt Chrome đạt**, không có page error. Dependencies tương thích theo `uv pip check`.

Các kết quả máy đọc được nằm trong [evidence](evidence/), ảnh nằm trong [screenshots](../screenshots/README.md). Tests dùng LangGraph và SQLite thật cùng backend giả; không được coi là API execution.

[validation.json](evidence/validation.json) ghi output kiểm tra cuối và SHA-256 của source/artifacts. Hash của lần gọi live được giữ nguyên trong `live_runs.json`; lần đó diễn ra trước các chỉnh sửa serializer checkpoint, audit và UI cuối. Không thay hash lịch sử để giả định đã chạy lại API trên source cuối. Offline evidence được chạy lại sau khi hoàn thiện; browser mở lại các checkpoint live đã có.

## Hai PR thật

Các hàng dưới là hai checkpoint live được dùng trong UI. Lần kiểm tra CLI Exercise 1 riêng ở [exercise1_runs.json](evidence/exercise1_runs.json) dùng đúng hai lệnh `uv run python exercises/exercise_1_confidence.py --pr ...` của đề, lấy PR và gọi YesScale thật: PR #1 **65% → pending_human_approval**, PR #2 **55% → pending_escalation**. Cả hai in đúng nhánh mong đợi; graph Exercise 1 chỉ kết thúc ở placeholder, không interrupt hay đăng comment. Mười tests về biên ngưỡng và ba nhánh graph đều đạt. Giữ nguyên `common/` và ngưỡng 0.58/0.73; không ép nhánh theo ID PR. Confidence mới được giữ riêng, không ghi đè số 0.50 của lần chạy UI trước.

| PR | Model được request | Confidence | Nhánh thực tế | Trạng thái |
|---|---|---|---|---|
| [PR-Demo #1](https://github.com/VinUni-AI20k/PR-Demo/pull/1) | `gpt-4o-mini` qua YesScale | 0.65 | `human_approval` | Chờ reviewer |
| [PR-Demo #2](https://github.com/VinUni-AI20k/PR-Demo/pull/2) | `gpt-4o-mini` qua YesScale | 0.50 | `escalate` | Chờ trả lời câu hỏi |

[live_runs.json](evidence/live_runs.json) chứa analysis, diff, head SHA, thread và audit thực tế. PR #1 thiếu xác nhận migration và validation priority. PR #2 có MD5, cơ chế token và lưu token chưa an toàn; model đặt câu hỏi về chính sách mật khẩu, token và `user_id` mặc định.

Đây là kết quả quan sát, không ép confidence theo PR ID. Provider model ID là provenance của request, chưa xác minh snapshot phía provider. Nhận xét model cần người đọc kiểm tra: chẳng hạn đề xuất chỉ đổi SHA-1 sang SHA-256 chưa đủ chứng minh token khó đoán; cần CSPRNG, entropy, expiry, rotation và quyền truy cập đúng. Model cũng có thể bỏ sót finding, nên confidence không thay thế review bảo mật.

Hai phiên live được mở lại trong process Streamlit/Chrome khác từ SQLite mà không gọi LLM lần nữa. Chưa có phản hồi con người hoặc bình luận GitHub trong các phiên live. Review được giữ để người dùng kiểm tra trước khi xuất bản.

## HITL và phiên bền

`interrupt()` trả payload chứa diff, summary, reasoning, comments hoặc câu hỏi. Resume dùng đúng thread với `Command(resume=...)`. `AsyncSqliteSaver` được mở/đóng trong cùng event loop cho từng thao tác; mở thread đã có chỉ đọc checkpoint hoặc tiếp tục chỗ đang dừng, không gửi input khởi tạo lần nữa.

Edit yêu cầu nội dung mới, lưu thành draft rồi xác nhận. Reject không gọi publication adapter. Escalation lấy Q&A làm ngữ cảnh, giữ nguyên finding chưa giải quyết, rồi yêu cầu final confirm. Confidence sau synthesize có thể thấp hơn; code không tăng điểm giả.

Audit ghi fetch, analyze, route, automatic decision, pending HITL, reviewer response, synthesize/edit và commit/reject/failure. `reviewer_id` chỉ có ở sự kiện reviewer; nó là attribution cấu hình, không phải identity được xác thực. Thời gian `execution_time_ms` đo bằng monotonic cho lần chạy node, không đại diện tổng thời gian người duyệt chờ. Pending event được kiểm tra để không lặp khi node interrupt chạy lại trong luồng tuần tự.

## Kiểm chứng offline và UI

- Biên 0.58 và 0.73 được kiểm thử cùng điểm ngay dưới ngưỡng.
- Đóng/mở saver và graph mới vẫn khôi phục payload; không fetch/analyze thêm khi reload.
- Edit hiển thị đúng nội dung đã sửa, bắt xác nhận; reject không gửi comment.
- Escalation từ chối câu trả lời trống/thiếu và không tự commit sau synthesize.
- Stub publication xác minh POST đúng một lần khi resume bình thường; lỗi publication được log `failed`, không hiện success và không ghi nguyên exception có thể chứa secrets.
- Chrome thử approval, edit/confirm, escalation/validation/refine/reject, automatic preview, reload, hai live checkpoints và viewport 375px/reduced motion.

Demo dùng fixture rõ ràng; các câu trả lời trong `offline_runs.json` là **phản hồi kiểm thử tự động**, không phải lời người dùng phê duyệt PR thật. Ảnh `07`/`08` là phiên live; các ảnh luồng hoàn tất dùng demo có nhãn.

## Khác biệt có chủ ý so với starter

1. Ngưỡng dùng hằng số 0.73/0.58, sửa sự lệch giữa TODO cũ và README.
2. Dùng SQLite theo starter, chưa làm PostgreSQL; giữ `common/` và `audit/` nguyên bản.
3. Thêm xác nhận cuối sau synthesis, đúng yêu cầu UI Exercise 5.
4. Preview là mặc định; publication cần checkbox hoặc `--publish`. Không gán draft thành kết quả đã đăng.
5. Hỗ trợ YesScale qua tên biến OpenAI-compatible mà không sửa LLM factory được cấp.
6. Sidebar quy đổi mức rủi ro thành số trước `MAX`; tránh so sánh chữ `high/low/med` theo alphabet.

## Giới hạn và hướng production

SQLite và UI localhost phù hợp lab, chưa có reviewer authentication, RBAC, distributed locks hoặc PostgreSQL migration. Audit không phải log bất biến có chữ ký. Không bảo đảm exactly-once trên cửa sổ crash giữa API GitHub và checkpoint; cần durable outbox, marker reconciliation và kiểm tra head SHA trước publish. Các session đã hoàn tất không đăng lại khi chỉ reload.

LLM sử dụng diff và câu trả lời như dữ liệu không tin cậy, nhưng prompt instruction chưa đủ chứng minh chống prompt injection. Cần kiểm soát quyền, giới hạn input, kiểm thử bảo mật và bảo vệ secrets ở môi trường triển khai. Bonus time-travel, calibration và multi-reviewer chưa triển khai; không thuộc năm bài bắt buộc.
