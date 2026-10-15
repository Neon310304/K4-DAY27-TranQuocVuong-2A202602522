# Phạm vi bằng chứng

- `live_runs.json`: hai lần fetch GitHub và phân tích YesScale thật, có timestamp, requested model, diff/head SHA, analysis, interrupt và audit. Giữ nguyên source hashes tại thời điểm thực thi; cả hai phiên đang chờ reviewer, không có bình luận được đăng.
- `offline_runs.json`: graph chạy với fixture tổng hợp và câu trả lời do script kiểm thử tự nhập. Có ba nhánh và final confirm sau escalation. Không phải nhãn người hoặc lời phê duyệt PR thật.
- `browser_checks.json`: tám kiểm tra Chrome, gồm tương tác demo, reload SQLite, mở checkpoint của hai lần chạy live và viewport 375px. Không tạo thêm LLM request live.
- `browser_controls.json`: các nút thực tế được đọc từ DOM khi kiểm tra giao diện.
- `validation.json`: command/output/exit code của kiểm tra cuối, source hashes hiện tại và hashes của evidence/ảnh. Danh sách khác biệt so với source hashes live được giữ rõ; không thay metadata lịch sử. Đây là kết quả công cụ tự ghi, không phải chứng thực độc lập.
- `setup.json`: kiểm tra sau khi đổi tên fork/thư mục sang `K4-DAY27...`, cài môi trường mới, xác thực GitHub và mở lại checkpoint. Ghi rõ Credential Manager được dùng thay PAT classic riêng; không chứa token và không gọi thêm LLM hoặc đăng comment.

Các ảnh trong `screenshots/` được chụp ở lần kiểm tra browser sau chỉnh sửa UI; source text sau đó được chuẩn hoá xuống dòng LF. Hash lịch sử có thể khác cả do thay đổi code lẫn xuống dòng. `validation.json` không bao gồm hash của chính nó, tránh tham chiếu vòng.

SQLite và `.env` chỉ tồn tại trên máy, bị Git bỏ qua. Người clone repo chạy được demo và tests không cần key; muốn tạo checkpoint live mới thì cấu hình key riêng, chạy script live rồi kiểm tra output, không coi JSON có sẵn là một lần gọi API mới.
