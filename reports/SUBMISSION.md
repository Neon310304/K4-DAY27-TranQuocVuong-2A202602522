# Day27 — kiểm tra trước khi nộp

**Trần Quốc Vượng · 2A202602522**

Link fork nộp bài: https://github.com/Neon310304/K4-DAY27-TranQuocVuong-2A202602522

- [x] Fork đúng tên, thuộc Neon310304, Public; mở không đăng nhập trả HTTP 200.
- [x] Đủ bốn exercise, `app.py`, `common/`, `audit/`, `pyproject.toml`, `.env.example`; không còn TODO hoặc `NotImplementedError` trong phần triển khai.
- [x] `.env` và `*.db` được ignore, không nằm trong Git.
- [x] Clone sạch commit `cfbe05e`, tạo `.env` từ mẫu, `uv sync` thành công; **47 tests pass trên Python 3.11.15**.
- [x] Bốn entrypoint CLI và `audit.replay` import được qua `--help`; CLI Exercise 4 chạy demo → reject → replay/list thành công. Các test graph/API adapter là offline, không giả thành gọi API thật từ clone sạch.
- [x] Streamlit từ clone sạch chạy demo, reload giữ checkpoint, Reject hoàn tất; SQLite chỉ có một fetch/analyze cho thread kiểm thử. Không cần key thật cho phần này.
- [x] Người dùng đã chọn Approve cho [bản review PR #1](drafts/exercise2-review.md). Phiên CLI Exercise 2 resume và đạt `committed`; [comment công khai dưới Neon310304](https://github.com/VinUni-AI20k/PR-Demo/pull/1#issuecomment-6187698906) khớp bản đã duyệt, chỉ có một comment khớp marker. [Bằng chứng xác minh](evidence/github_publication.json).

[Bằng chứng máy đọc được](evidence/submission_check.json) ghi command, exit code, phiên bản Python, kiểm tra browser/SQLite và phạm vi thực thi. Các lần gọi GitHub/YesScale thật của bài nằm riêng trong [evidence](evidence/README.md).

Repo đã đủ các mục kiểm tra ở trên để nộp link fork vào form của lớp. Chưa có xác nhận đã nộp form Day27; không coi việc push GitHub là đã nộp trên hệ thống lớp.
