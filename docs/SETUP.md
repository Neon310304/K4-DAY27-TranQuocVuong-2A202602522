# Chuẩn bị Day27

Repo nộp: https://github.com/Neon310304/K4-DAY27-TranQuocVuong-2A202602522. Đây là fork public của `VinUni-AI20k/VinUni-AI20k-Day27-Track03-HITL`.

Checkout đang dùng trên Windows: `D:\Python\K4-DAY27-TranQuocVuong-2A202602522`. Thư mục cũ `K--DAY27...` vẫn được giữ vì editor đang mở nó; không xoá file khi editor có thể còn dữ liệu chưa lưu. Dùng thư mục mới cho các lệnh tiếp theo.

```powershell
cd D:\Python\K4-DAY27-TranQuocVuong-2A202602522
uv sync --locked --group dev
git remote -v
```

Chỉ sao chép `.env.example` khi chưa có `.env`. Bản `.env` hiện có đã được giữ nguyên key riêng và bổ sung các tên biến mà starter đọc:

- `OPENROUTER_API_KEY`: key YesScale hiện có, được gửi tới endpoint YesScale do `LLM_BASE_URL` chỉ định. Tên biến này không làm key YesScale trở thành key của OpenRouter.
- `LLM_BASE_URL=https://api.yescale.io/v1`, `LLM_MODEL=gpt-4o-mini`.
- `GITHUB_USER=Neon310304` để ghi attribution reviewer.
- `HITL_PUBLISH_MODE=preview` áp dụng mặc định cho UI và CLI Exercise 3/4; muốn đăng comment, chọn checkbox Publish trước khi bắt đầu phiên hoặc dùng `--publish`. Riêng CLI Exercise 2 mặc định live theo đề: approve sẽ đăng thật; thêm `--preview` để thử với draft.

GitHub hiện lấy credential của tài khoản `Neon310304` từ Git Credential Manager vào bộ nhớ khi `GITHUB_TOKEN` để trống. Đã xác minh `/user` và quyền đọc `VinUni-AI20k/PR-Demo`, đều HTTP 200. Credential có các scope `gist, repo, workflow`, rộng hơn PAT classic `public_repo` được hướng dẫn trong đề. Không sao chép credential này vào `.env`.

Để khớp chính xác mục PAT trong checklist lớp, tạo token classic riêng tại https://github.com/settings/tokens/new, đặt hạn 30 ngày, chỉ chọn `public_repo`, rồi tự điền `GITHUB_TOKEN` trong `.env`. Không gửi token qua chat, không ghi vào source/ảnh. Khi biến này có giá trị, app ưu tiên nó thay Credential Manager. HTTP 200 khi đọc repo chỉ chứng minh quyền đọc; lần kiểm tra setup này không đăng comment và không chứng minh quyền POST bằng một comment thật.

`.env` bị Git bỏ qua. Kết quả kiểm tra không chứa giá trị key/token nằm trong [setup.json](../reports/evidence/setup.json). Các phiên live trước đó đã dùng YesScale thành công; kiểm tra setup mới không gọi LLM thêm và không đổi confidence hoặc threshold.
