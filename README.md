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
