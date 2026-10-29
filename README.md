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

## Model

Đường dẫn tính từ thư mục `ComfyUI/models/`.

### Bắt buộc (~42 GB)

| Thư mục | File | Dung lượng |
|---|---|---|
| `diffusion_models/` | [minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors](https://huggingface.co/smhfacct/Minimax-H3-fl2va-ref2va-hybrid-models/resolve/main/minimax_h3_hybrid_fl2va_ref2va_b25-49-int8.safetensors) | 21 GB |
| `text_encoders/` | [qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors) | 15,7 GB |
| `vae/` | [minimax_h3_video_vae_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_int8_convrot.safetensors) | 2,8 GB |
| `vae/` | [minimax_h3_audio_vae_fp32.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors) | 0,6 GB |
| `loras/` | [minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors](https://huggingface.co/lightx2v/Minimax-h3-Turbo/resolve/main/minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors) (Turbo LoRA mặc định) | 2 GB |

### Tùy chọn

| Tính năng | Thư mục | File | Dung lượng |
|---|---|---|---|
| Model H3 thay thế | `diffusion_models/` | [minimax_h3_ref2va_pruned_int8_convrot.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors) | 21 GB |
| VAE video fp16 | `vae/` | [minimax_h3_video_vae_fp16.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors) | 5,2 GB |
| Turbo LoRA | `loras/` | [minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors](https://huggingface.co/lightx2v/Minimax-h3-Turbo/resolve/main/minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors) | 2 GB |
| Turbo LoRA | `loras/` | [minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors](https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/main/loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors) | 2 GB |
| Turbo LoRA (FL2V) | `loras/` | [minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors](https://huggingface.co/lightx2v/Minimax-h3-Turbo/resolve/main/minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors) | 2 GB |
| Upscale latent | `latent_upscale_models/` | [minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors](https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler/resolve/main/minimax_h3_latent_upscaler_3d_conv_v1/minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors) | 0,7 GB |
| Upscale video SeedVR2 | `SEEDVR2/` | [seedvr2_ema_7b_fp16.safetensors](https://huggingface.co/numz/SeedVR2_comfyUI/resolve/main/seedvr2_ema_7b_fp16.safetensors) (tự tải ở lần chạy đầu) | 16,5 GB |
| Upscale video SeedVR2 | `SEEDVR2/` | [ema_vae_fp16.safetensors](https://huggingface.co/numz/SeedVR2_comfyUI/resolve/main/ema_vae_fp16.safetensors) (tự tải ở lần chạy đầu) | 0,5 GB |

Toàn bộ file gốc của H3: [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3).

### Custom node tùy chọn

| Tính năng | Node | Ghi chú |
|---|---|---|
| Upscale latent | [Comfyui_Minimax_h3_latent_Upscaler](https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler) | |
| Sage attention | [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | cần thêm gói pip `sageattention` (chỉ card NVIDIA) |
| Upscale video SeedVR2 | [ComfyUI-SeedVR2_VideoUpscaler](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler) + [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | |
| RTX Video Super Resolution | [Nvidia_RTX_Nodes_ComfyUI](https://github.com/Comfy-Org/Nvidia_RTX_Nodes_ComfyUI) + ComfyUI-VideoHelperSuite | không cần file model; chỉ card NVIDIA RTX |

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
