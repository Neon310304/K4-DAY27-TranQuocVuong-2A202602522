# Ảnh bằng chứng Day27

Các ảnh được chụp trực tiếp từ UI Streamlit chạy trên máy bằng Chrome headless qua Playwright; không dựng lại terminal hoặc sinh ảnh bằng AI. Ngày chụp: 15/10/2026. Không ảnh nào hiển thị key.

| Ảnh | Bằng chứng | Nguồn |
|---|---|---|
| [01-workspace](01-workspace.png) | Form PR và chế độ chạy | Offline UI |
| [02-approval](02-approval.png) | Diff/reasoning/comments và approval | Fixture tổng hợp |
| [03-edited-draft](03-edited-draft.png) | Nội dung thay thế sau Edit và confirm | Fixture tổng hợp |
| [04-escalation](04-escalation.png) | Câu hỏi cụ thể về auth | Fixture tổng hợp |
| [05-refined-review](05-refined-review.png) | Review sau Q&A vẫn chờ xác nhận | Fixture tổng hợp |
| [06-auto-preview](06-auto-preview.png) | Nhánh confidence cao | Fixture tổng hợp |
| [07-live-pr1](07-live-pr1.png) | PR thật #1, model trả 0.65 | GitHub + YesScale thật |
| [08-live-pr2](08-live-pr2.png) | PR thật #2, model trả 0.50 và câu hỏi | GitHub + YesScale thật |
| [09-mobile](09-mobile.png) | Viewport 375px, reduced motion | Mở checkpoint PR thật #2 |
| [10-session-audit](10-session-audit.png) | Phiên sidebar được khôi phục, bảng audit và lệnh replay | Fixture tổng hợp, audit đã đối chiếu SQLite |

Hai phiên thật vẫn chờ reviewer; các tương tác demo được script tự động nhập, không phải lời phê duyệt của sinh viên đối với PR thật. Xem [browser_checks.json](../reports/evidence/browser_checks.json) để đối chiếu phạm vi.

Tái tạo ảnh: tạo live checkpoints bằng `uv run python -m scripts.run_evidence --live` (gọi API, có chi phí), chạy Streamlit cổng 8527 với `HITL_DB_PATH=live_evidence.db` và `GITHUB_USER=automated-browser-validation`, rồi chạy `uv run python -m scripts.browser_evidence` với cùng database. Có thể đặt `HITL_BROWSER_BASE_URL` để dùng cổng khác; lần Exercise 5 dùng cổng 8528 riêng cho kiểm thử. Script ảnh chỉ mở lại checkpoint đã có, không gọi LLM live mới. [exercise5_browser.json](../reports/evidence/exercise5_browser.json) có audit tải thực từ browser, so khớp SQLite và output replay cho ba nhánh demo.
