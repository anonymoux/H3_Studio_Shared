# H3 Studio

Giao diện web gọn nhẹ cho workflow MiniMax H3 Ref2VA trong ComfyUI. Trang do chính ComfyUI phục vụ tại `http://127.0.0.1:8188/h3studio`.

- Ô soạn prompt hỗ trợ thẻ `<Picture N>` / `@image_N`, tự đánh số lại khi đổi thứ tự ảnh tham chiếu
- Tối đa 9 ảnh tham chiếu: kéo thả để tải lên, sắp xếp lại, rê chuột để xem ảnh phóng to
- Thiết lập: thời lượng, tỉ lệ khung hình, độ phân giải, seed, model (UNet), Turbo LoRA, sigma shift, scheduler, attention (có Sage qua KJNodes), kích thước ảnh tham chiếu
- Tùy chọn upscale latent hai giai đoạn (`MinimaxH3LatentUpscaler3D`) với split sigmas và decode theo ô (tiled)
- Bảng kết quả hiển thị tiến độ trực tiếp, nhãn trạng thái, hộp chi tiết (thời gian chờ / thời gian render) và trình xem video ở kích thước gốc
- Bản nháp và danh sách job được lưu trên server (`user/h3studio_state.json`) và đẩy tới các trang đang mở qua websocket của ComfyUI, nên script bên ngoài và trang web dùng chung một trạng thái

## Cài đặt

Chép thư mục này vào `ComfyUI/custom_nodes/` rồi khởi động lại ComfyUI. `workflow_api.json` là workflow MiniMax H3 Ref2VA dạng API mà trang dựa vào; nếu bạn đổi workflow gốc thì xuất lại file này.

Node tùy chọn: `Comfyui_Minimax_h3_latent_Upscaler` (upscale), `ComfyUI-KJNodes` (Sage attention).

## API

| Method | Đường dẫn | Chức năng |
|---|---|---|
| GET | `/h3studio/options` | danh sách model, LoRA, upscaler, kiểu attention có sẵn |
| GET | `/h3studio/state` | bản nháp + danh sách job (trạng thái job lấy mới từ ComfyUI) |
| PUT | `/h3studio/state` | `{draft: {...một phần}, source}` |
| POST | `/h3studio/queue` | đưa bản nháp hiện tại vào hàng đợi, trả về job |
| POST | `/h3studio/jobs/{id}/cancel` | dừng job đang chạy hoặc bỏ khỏi hàng đợi |
| DELETE | `/h3studio/jobs/{id}` | ẩn job khỏi danh sách (file video vẫn giữ) |
| GET | `/h3studio/upscale/options` | SeedVR2 / RTX có sẵn không, model DiT, giá trị mặc định |
| POST | `/h3studio/upscale` | `{video: {filename, subfolder, type}, options, parent?, source?}` → job có `summary.kind = "upscale"` |

## Upscale video

Mỗi video đã render xong có nút upscale. Nút này tạo một job riêng chạy SeedVR2 (khôi phục chi tiết tới cạnh ngắn mục tiêu, mặc định 1080p, model 7B fp16 có block swap) và/hoặc NVIDIA RTX Video Super Resolution (nhanh, ×1.5–×4), rồi lưu `output/video/H3Upscale_*.mp4` giữ nguyên frame rate và âm thanh của video gốc. Cần cài `seedvr2_videoupscaler` và/hoặc `Nvidia_RTX_Nodes_ComfyUI`; lần đầu dùng, SeedVR2 sẽ tự tải model về `models/SEEDVR2`.

## Cho AI Agent (Claude, …) điều khiển H3 Studio

Bản nháp và danh sách job nằm trên server, nên một AI agent có quyền chạy lệnh (Claude Code, Codex, Cursor, …) có thể tự viết prompt, tải ảnh tham chiếu, chạy job và tải video về chỉ bằng HTTP — không cần điều khiển trình duyệt. Trang H3 Studio đang mở sẽ tự cập nhật theo những gì agent làm, nên bạn vẫn theo dõi được tiến độ.

### Yêu cầu

- Agent chạy **trên cùng máy** với ComfyUI và gọi được `http://127.0.0.1:8188` (curl, Python `requests`, …).
- Nếu agent chạy ở máy khác trong mạng LAN: khởi động ComfyUI với `--listen 0.0.0.0` và thay `127.0.0.1` bằng IP máy chạy ComfyUI.
- ComfyUI **không có xác thực**. Đừng mở cổng 8188 ra Internet.

### Quy trình 5 bước

1. **Tải ảnh tham chiếu** (mỗi ảnh một lần, thứ tự tải = `<Picture 1>`, `<Picture 2>`, …):

   ```bash
   curl -F "image=@host.jpg" -F "type=input" -F "subfolder=h3studio" http://127.0.0.1:8188/upload/image
   # → {"name": "host.jpg", "subfolder": "h3studio", "type": "input"}
   ```

2. **Ghi bản nháp** — chỉ cần gửi những trường muốn đổi, các thiết lập khác giữ nguyên:

   ```bash
   curl -X PUT http://127.0.0.1:8188/h3studio/state -H "Content-Type: application/json" -d '{
     "source": "agent",
     "draft": {
       "prompt": "subject_definitions:\n<Subject 1> is the man in <Picture 1> ...",
       "refs": [{"id": "1", "name": "host.jpg", "subfolder": "h3studio", "label": "host.jpg"}],
       "duration": 10,
       "seed": 235895678739407,
       "seedRandom": false
     }
   }'
   ```

   Các trường hay dùng trong `draft`: `prompt`, `refs`, `duration` (giây), `aspect` (vd. `"9:16 (Portrait Widescreen)"`), `mp` (megapixel, vd. `0.5`), `seed`, `seedRandom`, `lora`, `upscale`, `upscaleBy` (`"scale"`/`"mp"`), `upscaleScale`. Gọi `GET /h3studio/state` để xem đầy đủ các trường hiện có, và `GET /h3studio/options` để biết tên model/LoRA hợp lệ.

3. **Chạy job:**

   ```bash
   curl -X POST http://127.0.0.1:8188/h3studio/queue -H "Content-Type: application/json" -d '{"source": "agent"}'
   # → job, có trường "id"
   ```

4. **Chờ kết quả:** gọi `GET /h3studio/state` khoảng mỗi 30–60 giây, tìm job theo `id`. `status` đi từ `queued` → `running` → `done` / `error` / `cancelled`. Một video H3 thường mất 10–40 phút tùy thời lượng và GPU.

5. **Tải video:** khi `status` là `done`, job có `videos: [{filename, subfolder, type}]`:

   ```bash
   curl -o out.mp4 "http://127.0.0.1:8188/view?filename=H3Studio_00001_.mp4&subfolder=video&type=output"
   ```

   (dùng đúng `filename`, `subfolder`, `type` trong job)

Hủy job: `POST /h3studio/jobs/{id}/cancel`. Upscale một video đã xong: `POST /h3studio/upscale` (xem bảng API ở trên).

### Câu lệnh mẫu giao cho agent

Dán đoạn sau cho Claude Code (hoặc agent khác) cùng với ảnh tham chiếu:

> H3 Studio đang chạy ở http://127.0.0.1:8188/h3studio. Đọc README tại https://github.com/anonymoux/H3_Studio_Shared để biết API. Hãy tải các ảnh `host.jpg`, `khach.jpg`, `boi-canh.jpg` làm `<Picture 1..3>`, viết prompt Ref2VA cho video 10 giây theo kịch bản dưới đây, chạy job với seed ngẫu nhiên, chờ xong rồi tải video về thư mục `clips/`. Không thay đổi các thiết lập khác trong bản nháp.

Lưu ý:
- Agent ghi đè **bản nháp đang mở** trên trang. Nếu bạn đang soạn dở, bảo agent lưu lại `GET /h3studio/state` trước khi ghi.
- Mỗi lần `queue`, workflow được dựng từ bản nháp lúc đó và gửi thẳng vào ComfyUI, nên sửa bản nháp sau khi queue không ảnh hưởng job đã gửi; agent có thể queue nối tiếp nhiều job.
