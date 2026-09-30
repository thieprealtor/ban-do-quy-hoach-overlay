# Chế độ trình duyệt (khi sandbox bị chặn mạng)

Dùng khi Overpass/tile Esri/CDN báo bị chặn từ shell (403/timeout). Toàn bộ xử lý chạy bằng `javascript_tool` trong Claude in Chrome. Thuật toán giống chế độ Python (`scripts/qh_overlay.py`): khớp theo mặt nước, kiểm tra bằng ảnh vệ tinh, xuất một GroundOverlay Bắc-lên.

## Môi trường

- Đừng cố vượt chặn mạng của sandbox; làm trong trình duyệt.
- Mở tab ngay tại URL ảnh (same-origin → canvas không bị taint). Từ tab earth.google.com, `fetch()` ảnh tuoitre/thuviennhadat và overpass-api.de đều qua CORS được → có thể build KMZ ngay trong tab Google Earth.
- Biến JS mất khi điều hướng tab: build xong phải tải/đưa file lên trước khi chuyển trang.
- Nếu `browser_batch` hoặc tool lỗi ngẫu nhiên, gọi lại từng lệnh riêng.
- Output tool bị chặn "[BLOCKED: Cookie/query string data]" khi trả về URL/chuỗi dài → chỉ trả về số đếm/tóm tắt.

## Nạp file vào trình duyệt

Dùng cho file người dùng gửi, ảnh render từ PDF, hoặc KMZ trên đĩa. Làm trong tab làm việc (nên là tab earth.google.com):
1. Tạo ô chọn file phụ:
   ```js
   document.getElementById('__src')?.remove();{const i=document.createElement('input');i.type='file';i.multiple=true;i.id='__src';i.setAttribute('aria-label','nguon-ban-do');i.style.cssText='position:fixed;top:0;left:0;z-index:99999';document.body.appendChild(i)};'ok'
   ```
2. Lấy ref của ô bằng `find`/`read_page`, gọi `file_upload` với `paths` là đường dẫn file (file gửi kèm, hoặc lưu ở thư mục làm việc/outputs; tổng < 10 MB mỗi lần). Không click vào ô — sẽ mở hộp thoại hệ thống.
3. Ảnh: nạp rồi ở lần gọi sau đọc `IMG.naturalWidth/Height`:
   ```js
   window.IMG=new Image();IMG.src=URL.createObjectURL(document.getElementById('__src').files[0]);'ok'
   ```
   Ảnh blob cùng origin nên canvas không bị taint. Khi đó giữ `window.IMG` này, không gán lại bằng `document.images[0]` ở helper bên dưới.
   KMZ để tải lên Google Earth: `window.__queue=[...document.getElementById('__src').files];` (xem mục cuối).

## Helper xem ảnh có thước tọa độ pixel

```js
window.IMG=document.images[0];
window.show=(x,y,w,h)=>{let c=document.getElementById('cv');if(!c){c=document.createElement('canvas');c.id='cv';c.style.cssText='position:fixed;left:0;top:0;z-index:9;background:#fff';document.body.appendChild(c);}c.width=innerWidth;c.height=innerHeight;const s=Math.min(c.width/w,c.height/h);const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,c.width,c.height);g.drawImage(IMG,x,y,w,h,0,0,w*s,h*s);g.font='14px sans-serif';g.fillStyle='red';const st=Math.pow(10,Math.floor(Math.log10(w/5)));for(let gx=Math.ceil(x/st)*st;gx<x+w;gx+=st)g.fillText(gx,(gx-x)*s+2,20);for(let gy=Math.ceil(y/st)*st;gy<y+h;gy+=st)g.fillText(gy,10,(gy-y)*s+5);return s};
```
Lưu ý: tọa độ screenshot ≠ CSS px (tỉ lệ = frame/innerWidth × scale screenshot). Tính quy đổi mỗi lần.

## Định vị (georeference)

Mô hình: phép đồng dạng (tịnh tiến + tỉ lệ + xoay) từ mét cục bộ sang pixel ảnh.
```js
window.LAT0=10.79; window.LON0=106.73; // tâm khu vực
window.KX=Math.cos(LAT0*Math.PI/180)*111320; window.KY=110574;
window.P={cx:0,cy:0,s:0.7,rot:0}; // s = px/m
window.toImg=(x,y)=>{const a=P.rot*Math.PI/180,c=Math.cos(a),s=Math.sin(a);return [P.cx+P.s*(c*x-s*y),P.cy+P.s*(s*x+c*y)]};
// world: x=(lon-LON0)*KX, y=(LAT0-lat)*KY
```

1. **Tỉ lệ ban đầu** từ thước tỉ lệ trên bản vẽ (đo số px cho 1000 m). Bản vẽ QH VN thường hướng Bắc lên (rot ≈ 0).
2. **Tải OSM** (đường chính + sông) qua Overpass từ trong trang:
   `[out:json][timeout:90];(way["highway"~"^(motorway|trunk|primary|secondary)$"](S,W,N,E);way["waterway"="river"](S,W,N,E););out geom;`
   Overpass hay lỗi/giới hạn → kiểm tra `text()` trước khi `JSON.parse`, thử lại.
3. **Vẽ OSM chồng lên ảnh**, chỉnh `cx,cy` cho khớp cao tốc/trục chính; dùng giao lộ có tên (điểm gần nhất giữa 2 đường theo `tags.name`) làm điểm khống chế.
4. **Tinh chỉnh tự động bằng mặt nước (cách tốt nhất khi có sông lớn):** tải `natural=water`/`waterway=riverbank` (+ relation, ghép ring theo đầu mút). Phân loại pixel ảnh: xanh nước `b>r+50&&b>150&&g>110` → +1; pixel màu đất quy hoạch (độ bão hòa `max−min>45`) → −1; bỏ trắng/xám, bảng biểu, chú thích. Raster polygon nước theo P lên canvas ¼ độ phân giải; điểm = (tổng pixel nước ảnh nằm trên nước OSM)/(số pixel nước) − (tổng pixel đất nằm trên nước OSM)/(số pixel đất). Coordinate descent trên cx, cy, s, rot với bước giảm dần (40→1 px, 3%→0.1%, 2°→0.05°). Hội tụ trong vài giây.
5. **Kiểm tra bằng ảnh vệ tinh**: vẽ tile Esri `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` (z=15; z=17 để soi chi tiết) + overlay alpha 0.55, chụp màn hình; bờ sông, cầu, cao tốc, trục đường phải trùng. Lệch rõ → quay lại bước 3–4. Mép thẳng bất thường → vùng che lẹm vào bản đồ.

## Xuất KMZ

- Crop vùng bản đồ (bỏ tiêu đề, bảng, chú thích, sơ đồ phụ bằng `clearRect` — che vừa khít, không lẹm), làm nền trắng trong suốt (`r,g,b>232 → alpha 0`). Nên bỏ luôn nền bản đồ xám bên ngoài ranh quy hoạch và dải sông trùng sông thật (satellite đã có) cho lớp phủ gọn.
- Nếu rot≠0: vẽ lại ảnh đã xoay vào canvas Bắc-lên theo `mpp` (m/px ≈ 1/P.s, đừng upsample) rồi tính LatLonBox từ bbox thế giới: `north=LAT0-wy0/KY, south=LAT0-wy1/KY, west=LON0+wx0/KX, east=LON0+wx1/KX`.
- KML: một `GroundOverlay`, `<color>ddffffff</color>`, `<Icon><href>files/overlay.png</href></Icon>`, `<LatLonBox>`, description ghi nguồn + số QĐ + "định vị gần đúng, sai số ~20–50 m, chỉ tham khảo".
- Đóng gói ZIP store-only (tự viết CRC32 + local header/central directory, cờ UTF-8 0x0800) thành `.kmz`, `doc.kml` là mục đầu tiên. Giữ PNG ≤ ~10 MB.
- Đặt tên file: `QHPK<số>_<Khu>_overlay.kmz`.

## Giao file

- **Tải về máy**: tạo `<a download>` từ blob và click → file vào thư mục Downloads. Nói rõ tên file + vị trí (Ctrl/Cmd+J để mở danh sách tải xuống).

## Tải lên Google Earth

1. Có sẵn `File` trong trang: KMZ build ngay trong tab earth.google.com (fetch ảnh qua CORS), hoặc file trên đĩa nạp qua ô file phụ (mục "Nạp file vào trình duyệt"). Đưa vào hàng đợi `window.__queue=[...]`.
2. Trang chủ Dự án → **Mới → Dự án bản đồ mới**.
3. Không được click để mở hộp chọn file hệ thống. Chặn `click()` của input file để nạp sẵn file:
   ```js
   window.__queue=window.__queue||[FILE];
   const hc=HTMLElement.prototype.click;
   HTMLInputElement.prototype.click=function(){if(this.type==='file'&&__queue.length){const dt=new DataTransfer();dt.items.add(__queue.shift());this.files=dt.files;this.dispatchEvent(new Event('input',{bubbles:true}));this.dispatchEvent(new Event('change',{bubbles:true}));return}return hc.call(this)};
   ```
   Sau đó mở menu **Tệp → Nhập tệp → Tải lên từ thiết bị**; hộp thoại hỏi cách thêm → chọn **Đối tượng trên bản đồ** → **Hoàn tất**. Lặp lại cho từng file.
4. Đổi tên dự án: triple-click ô tiêu đề, gõ tên, Tab. Dự án tự lưu vào Google Drive.
5. Chụp màn hình xác nhận lớp phủ hiển thị đúng chỗ. Đóng tab phụ.
