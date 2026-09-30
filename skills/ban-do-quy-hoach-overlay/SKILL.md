---
name: "ban-do-quy-hoach-overlay"
description: "Tạo lớp phủ bản đồ quy hoạch (KMZ) từ ảnh/PDF bản đồ QHPK/QHSDĐ công bố chính thức, tự định vị lên Google Earth theo sông và đường OpenStreetMap, kèm ranh giới phường/xã và ảnh kiểm tra trên nền vệ tinh; có thể tải thẳng vào dự án Google Earth. Dùng khi cần 'làm lớp phủ quy hoạch', 'đưa bản đồ quy hoạch lên Google Earth', 'map quy hoạch', 'KMZ quy hoạch', hoặc xem quy hoạch một phường/xã/khu vực trên nền vệ tinh."
---

# Lớp phủ bản đồ quy hoạch lên Google Earth

Biến ảnh bản đồ quy hoạch (phân khu 1/2000, QH sử dụng đất…) thành lớp phủ KMZ đặt đúng tọa độ, rồi giao file hoặc tải vào dự án Google Earth web của người dùng. Trả lời người dùng bằng tiếng Việt, ngắn gọn.

## 0. Nguyên tắc nguồn dữ liệu (bắt buộc)

- CHỈ dùng bản đồ quy hoạch do cơ quan nhà nước công bố (Sở QH-KT/Sở Xây dựng, UBND, Viện QHXD) hoặc bản báo chí đăng lại nguyên bản công bố (Tuổi Trẻ, Thư viện Nhà đất…).
- KHÔNG sao chép, tải KML, vẽ lại hay "làm giống" bản đồ My Maps/Google Earth của cá nhân khác, nhất là khi tác giả ghi bản quyền hoặc tắt xuất KML (lỗi 403). Khi gặp trường hợp này: nói rõ lý do, gợi ý xin tác giả hoặc dùng nguồn chính thức.
- Dữ liệu GIS của Sở TN&MT (geoportal) thường giới hạn dùng phi lợi nhuận: không dùng cho mục đích môi giới nếu chưa có chấp thuận.
- Luôn ghi nguồn + số quyết định (nếu có) vào mô tả lớp phủ và vào câu trả lời.

## 1. Chọn nguồn bản đồ

**Hỏi nguồn trước khi tìm.** Gửi đúng một câu rồi dừng, chờ người dùng trả lời. Ví dụ:

> Đã có sẵn nguồn bản đồ quy hoạch chưa (link bài viết, link ảnh, file PDF, file ảnh)? Có thì gửi vào đây để dùng luôn; chưa có thì sẽ tự tìm trên cổng thông tin nhà nước và báo chí uy tín.

- Yêu cầu đã kèm link/file → không hỏi, làm **1A**.
- Yêu cầu đã nói "tự tìm", hoặc người dùng trả lời không có / không kèm nguồn → làm **1B**.

### 1A. Người dùng đưa nguồn

- **Link bài viết/trang web**: lấy URL ảnh gốc trong bài (xem 1B bước 2); trang chỉ có PDF đính kèm → xử lý như PDF.
- **Link ảnh**: tải thẳng.
- **PDF** (file gửi kèm, hoặc link PDF tải bằng `curl`; tải bị chặn thì nhờ người dùng tải về rồi gửi file):
  - Chọn trang bản đồ: khổ giấy lớn nhất hoặc có chữ "SỬ DỤNG ĐẤT"; không chắc thì hỏi số trang.
  - Render ra JPEG chất lượng ~90, cạnh dài ~6000 px: `pdftoppm -f <trang> -l <trang> -r <dpi> -jpeg -jpegopt quality=90 -singlefile in.pdf out`, với dpi ≈ 6000×72 / cạnh dài trang tính bằng pt (xem `pdfinfo`); hoặc PyMuPDF `page.get_pixmap(dpi=…)`.
  - Bản scan: trích ảnh gốc nếu nét hơn (`pdfimages -png -j -f <trang> -l <trang> in.pdf img`).
- **File ảnh**: dùng luôn.

Nguồn người dùng đưa vẫn theo mục 0: My Maps/KML của cá nhân khác hoặc dữ liệu geoportal hạn chế → nói rõ lý do, đề nghị nguồn chính thức. Ghi nguồn là link hoặc tên file, kèm cơ quan ban hành + số QĐ; không rõ xuất xứ thì hỏi lại, hoặc ghi "nguồn do người dùng cung cấp, chưa xác minh".

### 1B. Tự tìm trên nguồn uy tín

Ưu tiên:
1. Cổng thông tin nhà nước: Sở Quy hoạch – Kiến trúc / Sở Xây dựng, UBND tỉnh/TP, phường/xã, Viện Quy hoạch xây dựng.
2. Báo chí chính thống đăng lại nguyên bản công bố: Tuổi Trẻ, Thanh Niên, VnExpress, Người Lao Động, Thư viện Nhà đất…

Không dùng: bản vẽ lại trên trang môi giới, group/fanpage, My Maps/KML cá nhân (mục 0).

1. Xác định phạm vi: phường/xã mới (sau sắp xếp 1/7/2025) thường gồm nhiều phường cũ và nằm trên **nhiều phân khu** → tìm thành phần phường (`<tên phường> gồm những phường nào sau sáp nhập`) rồi các phân khu phủ lên nó; làm đủ các phân khu liên quan.
2. WebSearch: `quy hoạch phân khu số N <quận/TP> bản đồ quy hoạch sử dụng đất <năm>`, `công bố đồ án quy hoạch phân khu …`, `site:gov.vn quy hoạch phân khu <khu vực>`. Lấy URL ảnh gốc độ phân giải cao trong bài: tải HTML bằng `curl` rồi lọc `<img>` (thuộc tính `data-original`/`src`), hoặc trong trình duyệt:
   ```js
   [...document.querySelectorAll('img')].map(i=>i.getAttribute('data-original')||i.currentSrc||i.src).filter(s=>/qhpk|qhsdd|phan-khu|pano/i.test(s))
   ```
   Ảnh báo thường là bản thu nhỏ: bỏ đoạn `thumb_w/<n>/` hoặc `zoom/<w>_<h>/` trong URL để lấy ảnh gốc (Tuổi Trẻ: `https://cdn2.tuoitre.vn/<id>/<yyyy>/<m>/<d>/<tên>.jpg`).
3. Số quyết định thường KHÔNG in trên ảnh (khung tên để trống): tìm `"phân khu số N" <địa phương> "QĐ-UBND"`. Nguồn có thể ghi lệch ngày ký/ngày công bố → ghi rõ ngày nào là ngày nào.
4. Tìm điều chỉnh mới hơn: `điều chỉnh quy hoạch <khu vực> <năm nay>`, `điều chỉnh cục bộ phân khu số N`. Có điều chỉnh → ghi vào mô tả lớp phủ và báo cáo.
5. Báo người dùng một dòng nguồn đã chọn (cơ quan/báo + số QĐ), rồi làm tiếp.

## 2. Chọn cách chạy

Kiểm tra mạng từ shell:
```bash
for u in https://overpass-api.de/api/status "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/15/15435/26005" "<URL ảnh>"; do curl -s -o /dev/null -m 15 -w "%{http_code} $u\n" "$u"; done
```
- Tất cả 200 → **chế độ Python** (mục 3): nhanh, ổn định, dùng script có sẵn.
- Ảnh bị chặn nhưng Overpass/Esri được → nhờ người dùng tải ảnh rồi gửi file, vẫn dùng chế độ Python.
- Overpass/Esri bị chặn (sandbox cloud 403/timeout) → **chế độ trình duyệt**: làm theo `references/browser-mode.md`.

## 3. Chế độ Python (`scripts/qh_overlay.py`)

Chuẩn bị (thư mục làm việc riêng cho mỗi lần chạy):
```bash
S="<thư mục skill>/scripts/qh_overlay.py"
if command -v uv >/dev/null; then PY="uv run"
elif python3 -c "import numpy,scipy,shapely,PIL" 2>/dev/null; then PY=python3
else python3 -m venv .qhvenv && .qhvenv/bin/pip install -q numpy scipy shapely pillow && PY=.qhvenv/bin/python; fi
```

1. **Tải ảnh**: `curl -sL -A "Mozilla/5.0" -e "<URL bài viết>" -o pk1.jpg "<URL ảnh gốc>"`. Cạnh ngắn < 2500 px → báo người dùng, tìm bản lớn hơn/PDF.
2. **Chọn vùng che** (tiêu đề, bảng biểu, chú giải, khung tên, sơ đồ phụ, thước tỉ lệ, la bàn):
   - `$PY "$S" grid pk1.jpg --out grid1.jpg` → xem ảnh, đọc tọa độ trên lưới (pixel ảnh gốc). Soi mép bằng `--crop x0,y0,x1,y1`.
   - `$PY "$S" masks pk1.jpg --exclude "x0,y0,x1,y1;..." --out masks1.png` → xám = che, xanh = nước, cam = đất quy hoạch.
   - Che **vừa khít** khung bảng; KHÔNG lẹm vào bản đồ (dễ lẹm ở chỗ bảng nằm sát sông/mép khu đất). Vùng ngoài ranh quy hoạch để trắng/xám thì không cần che.
3. **Tải OSM**: lấy bbox bằng `$PY "$S" geocode "<phường/khu vực>, <tỉnh/TP>" --margin-km 4`, nới thêm nếu bản đồ phân khu rộng hơn phường (bbox phải phủ **toàn bộ tờ bản đồ**, ≤ ~25×25 km). Rồi `$PY "$S" fetch-osm --bbox S,W,N,E --out osm.json`.
4. **Ranh giới** (khi hỏi theo phường/xã): `$PY "$S" boundary --bbox S,W,N,E --name "<tên phường>" --desc "<nghị quyết sắp xếp, thành phần>" --out RanhGioi_Phuong<Ten>.kml`. So diện tích in ra với số chính thức; lệch nhiều → có thể là ranh cũ, báo người dùng.
5. **Khớp tự động**: `$PY "$S" align pk1.jpg --osm osm.json --exclude "..." --out p1.json --check check1.jpg --boundary RanhGioi_...kml`
   - Xem `check1.jpg`: viền tím (mép nước OSM) phải trùng mép sông/kênh trên bản đồ, đỏ (đường chính) trùng trục đường. `score` ≥ 0.6 là tốt; < 0.5 là đáng ngờ.
   - Biết thước tỉ lệ (px cho 1000 m) → thêm `--scale-range <0.85·s>,<1.15·s>` với s = px/1000 để tìm nhanh và chắc hơn.
   - Không có sông lớn, hoặc khớp sai → dùng điểm khống chế: `$PY "$S" intersect --osm osm.json --road1 "<tên đường>" --road2 "<tên đường>"` lấy lat,lon giao lộ; đọc pixel cùng giao lộ trên ảnh lưới (`grid --crop`); chạy `align ... --gcp "u,v,lat,lon;u,v,lat,lon;..." [--refine]` với 3–5 điểm trải đều (ưu tiên trục hiện hữu, tránh đường quy hoạch mới). Sai số từng điểm ≤ ~30 m là đạt.
6. **Xuất KMZ**: `$PY "$S" export --params p1.json --osm osm.json --name "<QHPK … – khu>" --desc "Phê duyệt: QĐ …/QĐ-UBND ngày …; công bố …<br>Nguồn: <tên báo/cơ quan> – <URL><br><điều chỉnh mới nếu có>" --draw-order <n> --out QHPK<số>_<Khu>_overlay.kmz`
   - Script tự: lấy vùng quy hoạch (bỏ nền bản đồ xám bên ngoài), làm trong suốt nền trắng, bỏ dải sông vẽ trên bản đồ ở chỗ trùng sông thật (`--keep-river` để giữ), xoay Bắc-lên, PNG 256 màu (KMZ ~1–2 MB), ghi chú "sai số ~20–50 m, chỉ tham khảo".
   - Nhiều phân khu: lặp bước 2–6 cho từng tờ; phân khu chính của khu vực đặt `--draw-order` cao hơn.
7. **Kiểm tra vệ tinh**: `$PY "$S" verify --kmz A.kmz --kmz B.kmz --kml RanhGioi_...kml --out kiemtra.jpg` rồi xem ảnh. Soi thêm 2–3 điểm (cầu, khúc sông, nút giao lớn): `verify --kmz A.kmz --bbox S,W,N,E --zoom 17 --out ct1.jpg`.
   - Đạt: bờ sông, cầu, trục đường trùng trong ~50 m; không có mép thẳng bất thường (dấu hiệu vùng che lẹm vào bản đồ); không mất mảng đất nào.
   - Chưa đạt → quay lại bước 2 (vùng che) hoặc 5 (khớp).

## 4. Giao cho người dùng

**A. Gửi file** (mặc định): gửi các `.kmz`, file ranh giới `.kml` và ảnh kiểm tra bằng công cụ gửi file của môi trường (present_files/SendUserFile…), hoặc lưu vào thư mục người dùng chỉ định. Nói rõ tên file. Chế độ trình duyệt: xem `references/browser-mode.md` (tải bằng `<a download>`).

**B. Đưa thẳng vào Google Earth web** — chỉ khi người dùng yêu cầu (dùng tài khoản Google của họ, trong Claude in Chrome):
1. Mở `earth.google.com` → **Dự án** → **Mới → Dự án bản đồ mới**.
2. Nạp file từ đĩa mà KHÔNG click mở hộp chọn file hệ thống: tạo ô file phụ, dùng `file_upload` đưa các KMZ vào ô đó, chuyển sang hàng đợi, rồi chặn `click()` của ô file của Google Earth (chi tiết mã ở `references/browser-mode.md`, mục "Nạp file vào trình duyệt" và "Tải lên Google Earth").
3. Menu **Tệp → Nhập tệp → Tải lên từ thiết bị** → hộp thoại hỏi cách thêm → **Đối tượng trên bản đồ** → **Hoàn tất**. Lặp cho từng file (kể cả ranh giới).
4. Đổi tên dự án: triple-click ô tiêu đề, gõ tên (vd `QHPK Phường X (PK1 + PK7) - TP.HCM`), Tab. Dự án tự lưu vào Google Drive.
5. Chụp màn hình xác nhận lớp phủ hiển thị đúng chỗ.

## 5. Báo kết quả

Ngắn gọn: file/dự án đã tạo; mỗi phân khu phủ phần nào của khu vực; nguồn + số QĐ (+ ngày); điều chỉnh mới nếu có; cách bật/tắt và chỉnh độ mờ (Google Earth Pro: chuột phải lớp → Properties); độ phân giải (m/px) và sai số định vị; khuyên đối chiếu thông tin quy hoạch chính thức khi tư vấn lô cụ thể. Kèm ảnh kiểm tra và mục Sources với link bài/bản đồ gốc.

## Bẫy thường gặp

- Vùng che lẹm vào bản đồ → mất một dải đất, có mép thẳng trên ảnh kiểm tra (đã gặp ở Thảo Điền khi che bảng cơ cấu). Luôn xem `masks` và ảnh vệ tinh.
- Khớp sai điểm khống chế (đường quy hoạch mở rộng/tuyến mới ≠ đường hiện trạng trong OSM) → ưu tiên khớp mặt nước và trục hiện hữu.
- Phường mới (sau sắp xếp 2025) nằm trên nhiều phân khu → làm đủ các phân khu và kèm ranh giới phường để người dùng biết phần nào thuộc phường.
- Ảnh báo đăng là bản thu nhỏ → lấy URL gốc. Ảnh công bố thường chỉ ~2560 px (2–3,5 m/px): xem tổng thể, không đọc được chi tiết từng lô.
- Quy hoạch có thể đã điều chỉnh cục bộ sau khi công bố → luôn tìm tin điều chỉnh mới nhất.
- Overpass trả 406/429 khi request thiếu User-Agent mô tả rõ → script đã đặt UA và tự đổi máy chủ; tự viết request thì phải đặt UA.
- (Trình duyệt) Output tool bị chặn "[BLOCKED: Cookie/query string data]" khi trả về URL/chuỗi dài → chỉ trả về số đếm/tóm tắt. Đóng tab phụ sau khi xong.
