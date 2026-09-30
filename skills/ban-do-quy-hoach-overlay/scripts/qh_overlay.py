#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "scipy", "shapely>=2.0", "pillow"]
# ///
"""Định vị ảnh bản đồ quy hoạch (QHPK/QHSDĐ) lên Google Earth thành lớp phủ KMZ.

Tác giả: thieprealtor — https://github.com/thieprealtor/ban-do-quy-hoach-overlay

Lệnh con (chạy `python3 qh_overlay.py <lệnh> -h` để xem tham số):
  geocode    Tìm tọa độ + bbox gợi ý theo tên địa danh (Nominatim)
  grid       Ảnh lưới tọa độ pixel để chọn vùng che (bảng biểu, chú giải, tiêu đề...)
  masks      Xem phân loại nước/đất sau khi che, để soi vùng che có lẹm vào bản đồ không
  fetch-osm  Tải đường chính + mặt nước OpenStreetMap (Overpass) cho một bbox
  boundary   Tải ranh giới hành chính (phường/xã) theo tên -> KML
  intersect  Tọa độ giao lộ của 2 đường theo tên (dùng làm điểm khống chế)
  align      Tự khớp ảnh với mặt nước OSM (hoặc theo điểm khống chế --gcp)
  export     Xuất KMZ (GroundOverlay Bắc-lên, nền trong suốt, bỏ dải sông trùng sông thật)
  verify     Ảnh kiểm tra chồng lớp phủ lên nền vệ tinh Esri

Quy ước: pixel (u,v) tính trên ảnh gốc, gốc ở góc trên-trái. Hệ mét cục bộ: x hướng Đông,
y hướng Nam, gốc (lat0, lon0). Phép đồng dạng: u = cx + s(cos·x − sin·y), v = cy + s(sin·x + cos·y),
s = pixel/mét, rot = độ.
"""
import argparse
import io
import json
import math
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from xml.dom import minidom

try:
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage, signal
    from shapely.affinity import affine_transform
    from shapely.geometry import LineString, MultiPolygon, Polygon, box
    from shapely.ops import linemerge, polygonize, unary_union
    from shapely.ops import transform as shp_transform
except ImportError as e:  # pragma: no cover
    sys.exit(f'Thiếu thư viện ({e}). Cài: python3 -m pip install numpy scipy shapely pillow '
             f'(hoặc chạy bằng: uv run qh_overlay.py ...)')

Image.MAX_IMAGE_PIXELS = None
UA = 'ban-do-quy-hoach-overlay/1.1 (+https://github.com/thieprealtor/ban-do-quy-hoach-overlay)'
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.private.coffee/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
MAJOR = ('motorway', 'trunk', 'primary')


# ----------------------------------------------------------------- tiện ích
def floats(s, n=None):
    v = [float(t) for t in str(s).replace(' ', '').split(',') if t != '']
    if n and len(v) != n:
        sys.exit(f'Cần {n} số, nhận: {s}')
    return v


def rects(s):
    """'x0,y0,x1,y1;x0,y0,x1,y1' -> [(x0,y0,x1,y1), ...] (pixel ảnh gốc)."""
    out = []
    for part in (s or '').split(';'):
        if part.strip():
            x0, y0, x1, y1 = [int(round(v)) for v in floats(part, 4)]
            out.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
    return out


def norm(s):
    s = unicodedata.normalize('NFD', s or '').replace('đ', 'd').replace('Đ', 'D')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return ' '.join(s.lower().split())


def polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if g.geom_type == 'MultiPolygon':
        return list(g.geoms)
    if hasattr(g, 'geoms'):
        return [p for sub in g.geoms for p in polys(sub)]
    return []


def lines_of(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type in ('LineString', 'LinearRing'):
        return [g]
    if hasattr(g, 'geoms'):
        return [ln for sub in g.geoms for ln in lines_of(sub)]
    return []


class Frame:
    """Hệ mét cục bộ quanh (lat0, lon0): x Đông, y Nam."""

    def __init__(self, lat0, lon0):
        self.lat0, self.lon0 = float(lat0), float(lon0)
        self.kx = math.cos(math.radians(self.lat0)) * 111320.0
        self.ky = 110574.0

    def fwd(self, lon, lat):
        return (np.asarray(lon) - self.lon0) * self.kx, (self.lat0 - np.asarray(lat)) * self.ky

    def inv(self, x, y):
        return self.lon0 + np.asarray(x) / self.kx, self.lat0 - np.asarray(y) / self.ky

    def geom(self, g):
        return shp_transform(lambda x, y, z=None: self.fwd(x, y), g)


def to_img(g, P, q=1.0):
    """Hình học mét cục bộ -> pixel ảnh (chia q nếu ảnh đã thu nhỏ)."""
    a = math.radians(P['rot'])
    c, sn, s = math.cos(a), math.sin(a), P['s']
    return affine_transform(g, [s * c / q, -s * sn / q, s * sn / q, s * c / q, P['cx'] / q, P['cy'] / q])


def raster(geoms, size, fn=None):
    """Tô polygon (đã ở hệ pixel, hoặc qua hàm fn) -> mảng float32 0/1."""
    W, H = size
    img = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(img)
    ps = [p for g in geoms for p in polys(g)]
    conv = (lambda cs: [fn(x, y) for x, y in cs]) if fn else (lambda cs: list(cs))
    for p in ps:
        if len(p.exterior.coords) >= 3:
            d.polygon(conv(p.exterior.coords), fill=1)
    for p in ps:
        for it in p.interiors:
            if len(it.coords) >= 3:
                d.polygon(conv(it.coords), fill=0)
    return np.asarray(img, np.float32)


def reduce(m, q):
    H, W = m.shape
    H2, W2 = H // q, W // q
    return m[:H2 * q, :W2 * q].reshape(H2, q, W2, q).mean((1, 3)).astype(np.float32)


# ----------------------------------------------------------------- OSM
def http_get(url, data=None, timeout=60, headers=None):
    h = {'User-Agent': UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(query, timeout=240):
    last = None
    for ep in OVERPASS:
        for attempt in range(2):
            try:
                txt = http_get(ep, urllib.parse.urlencode({'data': query}).encode(), timeout,
                               {'Accept': 'application/json'}).decode('utf-8', 'replace')
                if txt.lstrip().startswith('{'):
                    return json.loads(txt)
                last = RuntimeError(txt[:200].replace('\n', ' '))
            except Exception as e:  # mạng/429/504: thử lại, rồi đổi máy chủ
                last = e
            time.sleep(4 * (attempt + 1))
    sys.exit(f'Overpass lỗi ở mọi máy chủ: {last}')


def _line(geom):
    return LineString([(p['lon'], p['lat']) for p in geom]) if geom and len(geom) >= 2 else None


def assemble(rel):
    """Ghép multipolygon relation (có 'geometry' từ `out geom`) thành (Multi)Polygon lon/lat."""
    outer, inner = [], []
    for m in rel.get('members', []):
        if m.get('type') != 'way' or 'geometry' not in m:
            continue
        ln = _line(m['geometry'])
        if ln is not None:
            (inner if m.get('role') == 'inner' else outer).append(ln)

    def build(ls):
        if not ls:
            return None
        ps = list(polygonize(linemerge(ls)))
        return unary_union(ps) if ps else None

    o = build(outer)
    if o is None:
        return None
    i = build(inner)
    return (o.difference(i) if i is not None else o).buffer(0)


def load_osm(path):
    d = json.load(open(path)) if isinstance(path, str) else path
    water, roads, wlines = [], [], []
    widths = {'river': 15.0, 'canal': 6.0, 'stream': 3.0}  # nửa bề rộng (m) khi chỉ có đường tâm
    for e in d['elements']:
        t = e.get('tags', {})
        if e['type'] == 'way':
            g = e.get('geometry')
            if not g:
                continue
            if t.get('natural') == 'water' or t.get('waterway') == 'riverbank':
                if len(g) >= 4 and g[0] == g[-1]:
                    water.append(Polygon([(p['lon'], p['lat']) for p in g]).buffer(0))
            elif 'highway' in t:
                roads.append((t.get('highway'), t.get('name', ''), _line(g)))
            elif t.get('waterway') in widths:
                wlines.append((t['waterway'], t.get('name', ''), _line(g)))
        elif e['type'] == 'relation' and (t.get('natural') == 'water' or t.get('waterway') == 'riverbank'):
            p = assemble(e)
            if p is not None and not p.is_empty:
                water.append(p)
    S, W, N, E = d.get('bbox', [None] * 4)
    fr = Frame((S + N) / 2, (W + E) / 2) if S is not None else None
    # thêm kênh/rạch chỉ có đường tâm (đệm theo bề rộng ước lượng, đổi sang độ)
    extra = []
    if fr is not None:
        for kind, _, ln in wlines:
            if ln is None:
                continue
            w = widths[kind]
            extra.append(ln.buffer(w / fr.ky, cap_style=2))
    wu = unary_union(water + extra)
    if S is not None:
        wu = wu.intersection(box(W, S, E, N))
    return wu, roads, wlines, fr, (S, W, N, E)


def cmd_fetch_osm(a):
    S, W, N, E = floats(a.bbox, 4)
    bb = f'{S},{W},{N},{E}'
    q = (f'[out:json][timeout:180];('
         f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]({bb});'
         f'way["waterway"~"^(river|canal|stream)$"]({bb});'
         f'way["natural"="water"]({bb});way["waterway"="riverbank"]({bb});'
         f'relation["natural"="water"]({bb});relation["waterway"="riverbank"]({bb}););out geom;')
    d = overpass(q)
    d['bbox'] = [S, W, N, E]
    with open(a.out, 'w') as f:
        json.dump(d, f)
    water, roads, wlines, fr, _ = load_osm(d)
    wa = fr.geom(water).area / 1e6 if not water.is_empty else 0
    print(f'OK {a.out}: {len(d["elements"])} phần tử, {len(roads)} đường, mặt nước {wa:.2f} km² trong bbox')
    if wa < 0.05:
        print('  Cảnh báo: gần như không có mặt nước -> tự khớp theo sông sẽ yếu; dùng --gcp khi align.')


def cmd_geocode(a):
    url = 'https://nominatim.openstreetmap.org/search?' + urllib.parse.urlencode(
        {'q': a.query, 'format': 'json', 'limit': 5, 'countrycodes': a.country})
    res = json.loads(http_get(url, timeout=30))
    if not res:
        sys.exit('Không tìm thấy địa danh; thử tên khác (vd thêm "Thành phố Hồ Chí Minh").')
    for i, r in enumerate(res):
        S, N, W, E = map(float, r['boundingbox'])
        lat = (S + N) / 2
        dy, dx = a.margin_km / 110.574, a.margin_km / (111.32 * math.cos(math.radians(lat)))
        tag = '  <- gợi ý' if i == 0 else ''
        print(f'{r["display_name"]}\n  tâm {float(r["lat"]):.5f},{float(r["lon"]):.5f}  '
              f'--bbox {S - dy:.4f},{W - dx:.4f},{N + dy:.4f},{E + dx:.4f}{tag}')


def cmd_boundary(a):
    S, W, N, E = floats(a.bbox, 4)
    if a.id:
        rid = int(a.id)
    else:
        d = overpass(f'[out:json][timeout:120];relation["boundary"="administrative"]({S},{W},{N},{E});out tags;')
        tgt = norm(a.name)
        cands = [r for r in d['elements'] if tgt in norm(r.get('tags', {}).get('name', ''))]
        if not cands:
            sys.exit(f'Không thấy ranh giới nào có tên chứa "{a.name}" trong bbox.')

        def rank(r):
            nm = norm(r['tags'].get('name', ''))
            exact = nm in (tgt, f'phuong {tgt}', f'xa {tgt}', f'thi tran {tgt}', f'dac khu {tgt}')
            return (0 if exact else 1, len(nm))
        cands.sort(key=rank)
        for r in cands[:6]:
            print(f'  ứng viên: id={r["id"]} admin_level={r["tags"].get("admin_level")} name={r["tags"].get("name")}')
        rid = cands[0]['id']
    g = overpass(f'[out:json][timeout:120];relation({rid});out geom;')
    rel = g['elements'][0]
    poly = assemble(rel)
    if poly is None or poly.is_empty:
        sys.exit('Không ghép được polygon ranh giới.')
    c = poly.centroid
    area = Frame(c.y, c.x).geom(poly).area / 1e6
    name = rel.get('tags', {}).get('name', a.name)
    ps = polys(poly.simplify(0.00002))

    def ring(r):
        return ' '.join(f'{x:.6f},{y:.6f},0' for x, y in r.coords)
    pm = ''.join(f'<Polygon><outerBoundaryIs><LinearRing><coordinates>{ring(p.exterior)}</coordinates>'
                 f'</LinearRing></outerBoundaryIs></Polygon>' for p in ps)
    geom = pm if len(ps) == 1 else f'<MultiGeometry>{pm}</MultiGeometry>'
    desc = (a.desc + '<br>' if a.desc else '') + (
        f'Diện tích theo dữ liệu ~{area:.2f} km². Nguồn: OpenStreetMap (© OpenStreetMap contributors, ODbL), '
        f'relation {rid}. Chỉ tham khảo.')
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>Ranh giới {name}</name>
  <Style id="rg"><LineStyle><color>ff50ff00</color><width>3</width></LineStyle><PolyStyle><fill>0</fill></PolyStyle></Style>
  <Placemark>
    <name>{name}</name>
    <description><![CDATA[{desc}]]></description>
    <styleUrl>#rg</styleUrl>
    {geom}
  </Placemark>
</Document>
</kml>
'''
    minidom.parseString(kml.encode('utf-8'))
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(kml)
    print(f'OK {a.out}: {name} (relation {rid}, admin_level={rel.get("tags", {}).get("admin_level")}), '
          f'diện tích {area:.2f} km² -> so với số liệu chính thức để chắc là ranh giới mới nhất.')


def cmd_intersect(a):
    _, roads, _, _, _ = load_osm(a.osm)
    n1, n2 = norm(a.road1), norm(a.road2)
    g1 = unary_union([ln for _, nm, ln in roads if ln is not None and n1 in norm(nm)])
    g2 = unary_union([ln for _, nm, ln in roads if ln is not None and n2 in norm(nm)])
    if g1.is_empty or g2.is_empty:
        sys.exit('Không thấy một trong hai đường (chỉ có đường cấp tertiary trở lên trong osm.json).')
    inter = g1.intersection(g2)
    pts = [p for p in getattr(inter, 'geoms', [inter]) if p.geom_type == 'Point']
    if not pts:
        d = g1.distance(g2)
        sys.exit(f'Hai đường không cắt nhau trong dữ liệu (gần nhất ~{d * 111000:.0f} m).')
    seen = []
    for p in pts:  # gộp các điểm cách nhau < 40 m (nút giao nhiều nhánh)
        if all(math.hypot((p.x - q.x) * 109000, (p.y - q.y) * 110574) > 40 for q in seen):
            seen.append(p)
    for p in seen:
        print(f'{p.y:.6f},{p.x:.6f}')


# ----------------------------------------------------------------- ảnh
def build_masks(path, exclude, sat=45):
    im = np.asarray(Image.open(path).convert('RGB'))
    H, W, _ = im.shape
    valid = np.ones((H, W), bool)
    for x0, y0, x1, y1 in exclude:
        valid[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
    i16 = im.astype(np.int16)
    r, g, b = i16[..., 0], i16[..., 1], i16[..., 2]
    water = (b > r + 50) & (b > 150) & (g > 110) & valid
    colored = (i16.max(-1) - i16.min(-1)) > sat
    land = colored & ~water & valid
    return im, valid, water, land


def label_grid(img, x0, y0, scale, step):
    d = ImageDraw.Draw(img)
    W, H = img.size
    for gx in range(int(math.ceil(x0 / step) * step), int(x0 + W / scale) + 1, step):
        X = (gx - x0) * scale
        d.line([(X, 0), (X, H)], fill=(255, 0, 0), width=1)
        d.text((X + 2, 2), str(gx), fill=(255, 0, 0))
    for gy in range(int(math.ceil(y0 / step) * step), int(y0 + H / scale) + 1, step):
        Y = (gy - y0) * scale
        d.line([(0, Y), (W, Y)], fill=(255, 0, 0), width=1)
        d.text((2, Y + 2), str(gy), fill=(255, 0, 0))


def cmd_grid(a):
    im = Image.open(a.image).convert('RGB')
    print(f'Kích thước ảnh gốc: {im.size[0]} x {im.size[1]} px')
    x0, y0, x1, y1 = (floats(a.crop, 4) if a.crop else (0, 0, im.size[0], im.size[1]))
    c = im.crop((int(x0), int(y0), int(x1), int(y1)))
    k = min(1.0, a.max / max(c.size))
    c = c.resize((max(1, int(c.size[0] * k)), max(1, int(c.size[1] * k))))
    step = a.step or (100 if max(x1 - x0, y1 - y0) <= 2000 else 250)
    label_grid(c, x0, y0, k, int(step))
    for rx0, ry0, rx1, ry1 in rects(a.exclude):
        ImageDraw.Draw(c).rectangle([(rx0 - x0) * k, (ry0 - y0) * k, (rx1 - x0) * k, (ry1 - y0) * k],
                                    outline=(0, 90, 255), width=3)
    c.save(a.out, quality=88)
    print(f'OK {a.out} (lưới mỗi {step} px, nhãn là tọa độ ảnh gốc)')


def cmd_masks(a):
    im, valid, water, land = build_masks(a.image, rects(a.exclude), a.sat)
    vis = np.full(im.shape, 255, np.uint8)
    vis[land] = (240, 170, 60)
    vis[water] = (40, 110, 230)
    vis[~valid] = (170, 170, 170)
    H, W = water.shape
    k = min(1.0, a.max / max(H, W))
    Image.fromarray(vis).resize((int(W * k), int(H * k)), Image.NEAREST).save(a.out)
    print(f'OK {a.out}: nước {int(water.sum())} px, đất {int(land.sum())} px (xám = vùng che)')


# ----------------------------------------------------------------- khớp
class Aligner:
    def __init__(self, image, osm, exclude, sat=45):
        self.water_ll, self.roads, _, self.fr, self.bbox = load_osm(osm)
        self.WL = self.fr.geom(self.water_ll) if not self.water_ll.is_empty else self.water_ll
        S, W, N, E = self.bbox
        self.xmin, self.ymin = map(float, self.fr.fwd(W, N))
        self.xmax, self.ymax = map(float, self.fr.fwd(E, S))
        self.im, self.valid, self.water, self.land = build_masks(image, exclude, sat)
        self.H, self.W = self.water.shape

    def osm_raster(self, R):
        Wo, Ho = int((self.xmax - self.xmin) / R) + 1, int((self.ymax - self.ymin) / R) + 1
        return raster([self.WL], (Wo, Ho), lambda x, y: ((x - self.xmin) / R, (y - self.ymin) / R))

    def fft_eval(self, wq, lq, off_uv, q, O, R, s, rot, origin=None):
        """Điểm khớp tốt nhất theo tịnh tiến (FFT) với s, rot cố định. origin = tọa độ mét của O[0,0]."""
        xo, yo = origin or (self.xmin, self.ymin)
        u0, v0 = off_uv
        hq, wq_ = wq.shape
        sq = s / q
        a = math.radians(rot)
        c, sn = math.cos(a), math.sin(a)
        cu = np.array([u0, u0 + wq_, u0, u0 + wq_], float)
        cv = np.array([v0, v0, v0 + hq, v0 + hq], float)
        wx, wy = (c * cu + sn * cv) / sq, (-sn * cu + c * cv) / sq
        x0, y0 = wx.min(), wy.min()
        shp = (int((wy.max() - y0) / R) + 2, int((wx.max() - x0) / R) + 2)
        M = np.array([[sq * c * R, sq * sn * R], [-sq * sn * R, sq * c * R]])
        off = np.array([sq * (sn * x0 + c * y0) - v0, sq * (c * x0 - sn * y0) - u0])
        Ww = ndimage.affine_transform(wq, M, off, output_shape=shp, order=1, cval=0)
        Wl = ndimage.affine_transform(lq, M, off, output_shape=shp, order=1, cval=0)
        nw, nl = Ww.sum(), Wl.sum()
        if nw < 1 or nl < 1:
            return -9, None
        K = Ww / nw - Wl / nl
        C = signal.fftconvolve(O, K[::-1, ::-1], mode='full')
        i, j = np.unravel_index(np.argmax(C), C.shape)
        ro, co = i - (K.shape[0] - 1), j - (K.shape[1] - 1)
        T = np.array([xo + co * R - x0, yo + ro * R - y0])
        cx, cy = -s * (c * T[0] - sn * T[1]), -s * (sn * T[0] + c * T[1])
        return float(C[i, j]), dict(cx=float(cx), cy=float(cy), s=float(s), rot=float(rot))

    def search(self, s_lo, s_hi, rots):
        q = max(2, int(round(max(self.H, self.W) / 900)))
        wq, lq = reduce(self.water.astype(np.float32), q), reduce(self.land.astype(np.float32), q)
        ys, xs = np.nonzero((wq + lq) > 0)
        v0, v1, u0, u1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        wq, lq = wq[v0:v1, u0:u1], lq[v0:v1, u0:u1]
        ext = max(self.xmax - self.xmin, self.ymax - self.ymin)
        R1 = max(8.0, ext / 1000.0)
        O1 = self.osm_raster(R1)
        n = max(12, int(math.ceil(math.log(s_hi / s_lo) / math.log(1.05))) + 1)
        res = []
        for s in np.geomspace(s_lo, s_hi, n):
            for rot in rots:
                sc, P = self.fft_eval(wq, lq, (u0, v0), q, O1, R1, s, rot)
                if P:
                    res.append((sc, P))
        res.sort(key=lambda t: -t[0])
        top = []
        for sc, P in res:
            if all(abs(math.log(P['s'] / Q['s'])) > 0.04 or abs(P['rot'] - Q['rot']) > 0.6 or
                   math.hypot(P['cx'] - Q['cx'], P['cy'] - Q['cy']) > 150 * P['s'] for _, Q in top):
                top.append((sc, P))
            if len(top) == 4:
                break
        # vòng 2: lưới mịn hơn, chỉ quanh các ứng viên tốt nhất (cắt raster OSM quanh vùng phủ)
        R2 = max(4.0, R1 / 2.5)
        O2 = self.osm_raster(R2)
        cu_full = np.array([u0, u1, u0, u1], float) * q
        cv_full = np.array([v0, v0, v1, v1], float) * q
        best = (-9, None)
        for _, P in top:
            a_ = math.radians(P['rot'])
            c_, sn_ = math.cos(a_), math.sin(a_)
            du, dv = cu_full - P['cx'], cv_full - P['cy']
            fx, fy = (c_ * du + sn_ * dv) / P['s'], (-sn_ * du + c_ * dv) / P['s']
            m = 0.25 * max(np.ptp(fx), np.ptp(fy)) + 300
            i0 = max(0, int((fy.min() - m - self.ymin) / R2))
            i1 = min(O2.shape[0], int((fy.max() + m - self.ymin) / R2) + 1)
            j0 = max(0, int((fx.min() - m - self.xmin) / R2))
            j1 = min(O2.shape[1], int((fx.max() + m - self.xmin) / R2) + 1)
            if i1 - i0 < 4 or j1 - j0 < 4:
                continue
            Oc, origin = O2[i0:i1, j0:j1], (self.xmin + j0 * R2, self.ymin + i0 * R2)
            for f in np.linspace(0.94, 1.06, 7):
                for dr in (-0.5, 0.0, 0.5):
                    sc, Q = self.fft_eval(wq, lq, (u0, v0), q, Oc, R2, P['s'] * f, P['rot'] + dr, origin)
                    if Q and sc > best[0]:
                        best = (sc, Q)
        return best

    def score_fn(self, q):
        wq, lq = reduce(self.water.astype(np.float32), q), reduce(self.land.astype(np.float32), q)
        Nw, Nl = max(wq.sum(), 1e-6), max(lq.sum(), 1e-6)
        Hq, Wq = wq.shape
        clip = box(-50, -50, Wq + 50, Hq + 50)

        def f(P):
            g = to_img(self.WL, P, q).intersection(clip)
            O = raster([g], (Wq, Hq))
            return float((wq * O).sum() / Nw - (lq * O).sum() / Nl)
        return f

    def refine(self, P0):
        q = max(1, int(round(max(self.H, self.W) / 1800)))
        f = self.score_fn(q)
        P, best = dict(P0), f(P0)
        steps = {'cx': 40.0, 'cy': 40.0, 's': 0.03, 'rot': 2.0}
        mins = {'cx': 1.0, 'cy': 1.0, 's': 0.0008, 'rot': 0.05}
        while any(steps[k] >= mins[k] for k in steps):
            improved = False
            for k in steps:
                if steps[k] < mins[k]:
                    continue
                for sg in (1, -1):
                    Q = dict(P)
                    Q[k] = P[k] * (1 + sg * steps[k]) if k == 's' else P[k] + sg * steps[k]
                    sc = f(Q)
                    if sc > best + 1e-6:
                        P, best, improved = Q, sc, True
                        break
            if not improved:
                for k in steps:
                    steps[k] /= 2
        return best, P

    def from_gcp(self, gcps):
        A, bvec = [], []
        for u, v, lat, lon in gcps:
            x, y = self.fr.fwd(lon, lat)
            A += [[x, -y, 1, 0], [y, x, 0, 1]]
            bvec += [u, v]
        sol, *_ = np.linalg.lstsq(np.array(A, float), np.array(bvec, float), rcond=None)
        a_, b_, cx, cy = sol
        P = dict(cx=float(cx), cy=float(cy), s=float(math.hypot(a_, b_)), rot=float(math.degrees(math.atan2(b_, a_))))
        res = []
        for u, v, lat, lon in gcps:
            x, y = self.fr.fwd(lon, lat)
            pu = cx + a_ * x - b_ * y
            pv = cy + b_ * x + a_ * y
            res.append(math.hypot(pu - u, pv - v) / P['s'])
        return P, res

    def check_image(self, P, out, boundary=None):
        k = min(1.0, 1600 / max(self.H, self.W))
        img = Image.fromarray(self.im).resize((int(self.W * k), int(self.H * k)))
        d = ImageDraw.Draw(img)
        clip = box(-20, -20, img.size[0] + 20, img.size[1] + 20)
        for p in polys(to_img(self.WL, P, 1 / k).intersection(clip)):
            d.line(list(p.exterior.coords), fill=(255, 0, 255), width=2)
            for it in p.interiors:
                d.line(list(it.coords), fill=(255, 0, 255), width=2)
        for hw, _, ln in self.roads:
            if hw in MAJOR and ln is not None:
                for sub in lines_of(to_img(self.fr.geom(ln), P, 1 / k).intersection(clip)):
                    d.line(list(sub.coords), fill=(220, 0, 0), width=2)
        if boundary:
            for ring in read_kml_rings(boundary):
                ln = LineString(ring)
                for sub in lines_of(to_img(self.fr.geom(ln), P, 1 / k).intersection(clip)):
                    d.line(list(sub.coords), fill=(0, 170, 0), width=3)
        img.save(out, quality=88)


def cmd_align(a):
    ex = rects(a.exclude)
    al = Aligner(a.image, a.osm, ex, a.sat)
    t = time.time()
    if a.gcp:
        gcps = [floats(p, 4) for p in a.gcp.split(';') if p.strip()]
        if len(gcps) < 2:
            sys.exit('Cần ít nhất 2 điểm khống chế (nên 3–5 điểm trải đều).')
        P, res = al.from_gcp(gcps)
        print('Sai số từng điểm khống chế (m): ' + ', '.join(f'{r:.0f}' for r in res))
        score = al.score_fn(max(1, int(round(max(al.H, al.W) / 1800))))(P) if not al.WL.is_empty else float('nan')
        if a.refine and not al.WL.is_empty:
            score, P = al.refine(P)
    else:
        if al.WL.is_empty or al.water.sum() < 500:
            sys.exit('Ảnh hoặc OSM gần như không có mặt nước -> dùng --gcp "u,v,lat,lon;..."')
        if a.scale_range:
            s_lo, s_hi = floats(a.scale_range, 2)
        else:
            diag = math.hypot(al.xmax - al.xmin, al.ymax - al.ymin)
            s_lo, s_hi = max(al.H, al.W) / diag, max(al.H, al.W) / 500.0
        r0, r1 = floats(a.rot_range, 2)
        rots = list(np.arange(r0, r1 + 1e-9, 1.0))
        sc, P = al.search(s_lo, s_hi, rots)
        if P is None:
            sys.exit('Không tìm được vị trí khớp.')
        score, P = al.refine(P)
    P.update(lat0=al.fr.lat0, lon0=al.fr.lon0, score=round(score, 4) if score == score else None,
             image=os.path.abspath(a.image), exclude=ex, sat=a.sat, mpp=round(1 / P['s'], 3))
    with open(a.out, 'w') as f:
        json.dump(P, f, indent=1)
    lon, lat = al.fr.inv(*np.linalg.solve(
        [[P['s'] * math.cos(math.radians(P['rot'])), -P['s'] * math.sin(math.radians(P['rot']))],
         [P['s'] * math.sin(math.radians(P['rot'])), P['s'] * math.cos(math.radians(P['rot']))]],
        [al.W / 2 - P['cx'], al.H / 2 - P['cy']]))
    print(f'OK {a.out}: s={P["s"]:.4f} px/m ({1 / P["s"]:.2f} m/px), rot={P["rot"]:.2f}°, '
          f'score={P["score"]}, tâm ảnh ~ {float(lat):.5f},{float(lon):.5f} ({time.time() - t:.0f}s)')
    if P['score'] is not None and P['score'] < 0.5:
        print('  Cảnh báo: score thấp -> xem ảnh kiểm tra; nếu lệch, thêm --gcp hoặc thu hẹp --scale-range.')
    if a.check:
        al.check_image(P, a.check, a.boundary)
        print(f'  Ảnh kiểm tra: {a.check} (tím = mép nước OSM, đỏ = đường chính OSM)')


# ----------------------------------------------------------------- xuất KMZ
def cmd_export(a):
    P = json.load(open(a.params))
    image = a.image or P['image']
    ex = rects(a.exclude) if a.exclude is not None else [tuple(r) for r in P.get('exclude', [])]
    im, valid, water, land = build_masks(image, ex, P.get('sat', 45))
    H, W = water.shape
    r = max(6, int(round(min(H, W) / 210)))
    st = np.ones((3, 3), bool)
    area = ndimage.binary_closing((water | land) & valid, structure=st, iterations=r)
    area = ndimage.binary_fill_holes(area)
    lab, n = ndimage.label(area)
    if n > 1:
        sizes = ndimage.sum(area, lab, range(1, n + 1))
        area = lab == (1 + int(np.argmax(sizes)))
    area = ndimage.binary_opening(area, structure=st, iterations=max(2, r // 3)) & valid
    white = (im[..., 0] > 232) & (im[..., 1] > 232) & (im[..., 2] > 232)
    alpha = area & ~white
    if not a.keep_river:
        water_ll = load_osm(a.osm)[0]
        if not water_ll.is_empty:
            g = to_img(Frame(P['lat0'], P['lon0']).geom(water_ll), P).intersection(box(-50, -50, W + 50, H + 50))
            osm_w = raster([g], (W, H)) > 0
            osm_w = ndimage.binary_dilation(osm_w, iterations=max(2, int(round(10 * P['s']))))
            alpha &= ~(water & osm_w)
    rgba = Image.fromarray(np.dstack([im, alpha.astype(np.uint8) * 255]), 'RGBA')
    s, ang = P['s'], math.radians(P['rot'])
    c, sn = math.cos(ang), math.sin(ang)
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        sys.exit('Lớp phủ rỗng: kiểm tra vùng che (--exclude).')
    cu = np.array([xs.min(), xs.max() + 1, xs.min(), xs.max() + 1], float) - P['cx']
    cv = np.array([ys.min(), ys.min(), ys.max() + 1, ys.max() + 1], float) - P['cy']
    wx, wy = (c * cu + sn * cv) / s, (-sn * cu + c * cv) / s
    wx0, wy0 = wx.min(), wy.min()
    mpp = a.mpp or 1.0 / s
    Wn, Hn = int(math.ceil((wx.max() - wx0) / mpp)), int(math.ceil((wy.max() - wy0) / mpp))
    coef = (s * c * mpp, -s * sn * mpp, P['cx'] + s * c * wx0 - s * sn * wy0,
            s * sn * mpp, s * c * mpp, P['cy'] + s * sn * wx0 + s * c * wy0)
    out = rgba.transform((Wn, Hn), Image.AFFINE, coef, resample=Image.BICUBIC)
    fr = Frame(P['lat0'], P['lon0'])
    west, north = fr.inv(wx0, wy0)
    east, south = fr.inv(wx0 + Wn * mpp, wy0 + Hn * mpp)
    buf = io.BytesIO()
    while True:
        buf.seek(0)
        buf.truncate()
        out.quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(buf, 'PNG', optimize=True)
        if buf.tell() <= 9.5e6 or max(out.size) < 1500:
            break
        out = out.resize((int(out.size[0] * 0.8), int(out.size[1] * 0.8)), Image.LANCZOS)
    name = a.name or os.path.splitext(os.path.basename(a.out))[0]
    desc = (a.desc or '') + ('<br>' if a.desc else '') + (
        'Định vị gần đúng (khớp sông, đường theo OpenStreetMap), sai số ~20–50 m, chỉ tham khảo. '
        'Đối chiếu thông tin quy hoạch chính thức trước khi tư vấn lô cụ thể.')
    kml = f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{name}</name>
  <GroundOverlay>
    <name>{name}</name>
    <description><![CDATA[{desc}]]></description>
    <color>{a.color}</color>
    <drawOrder>{a.draw_order}</drawOrder>
    <Icon><href>files/overlay.png</href></Icon>
    <LatLonBox>
      <north>{float(north):.7f}</north>
      <south>{float(south):.7f}</south>
      <east>{float(east):.7f}</east>
      <west>{float(west):.7f}</west>
    </LatLonBox>
  </GroundOverlay>
</Document>
</kml>
'''
    minidom.parseString(kml.encode('utf-8'))
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('doc.kml', kml.encode('utf-8'))
        z.writestr('files/overlay.png', buf.getvalue())
    print(f'OK {a.out}: {out.size[0]}x{out.size[1]} px, {mpp * max(1, (Wn / out.size[0])):.2f} m/px, '
          f'{os.path.getsize(a.out) / 1e6:.2f} MB, N{float(north):.5f} S{float(south):.5f} '
          f'E{float(east):.5f} W{float(west):.5f}')


# ----------------------------------------------------------------- kiểm tra vệ tinh
def read_kmz(path):
    with zipfile.ZipFile(path) as z:
        kml_name = next(n for n in z.namelist() if n.lower().endswith('.kml'))
        doc = minidom.parseString(z.read(kml_name))
        out = []
        for go in doc.getElementsByTagName('GroundOverlay'):
            def val(tag):
                return float(go.getElementsByTagName(tag)[0].firstChild.data)
            href = go.getElementsByTagName('href')[0].firstChild.data.strip()
            img = Image.open(io.BytesIO(z.read(href))).convert('RGBA')
            out.append((img, dict(north=val('north'), south=val('south'), east=val('east'), west=val('west'))))
        return out


def read_kml_rings(path):
    doc = minidom.parse(path)
    rings = []
    for c in doc.getElementsByTagName('coordinates'):
        pts = [tuple(map(float, t.split(',')[:2])) for t in c.firstChild.data.split()]
        if len(pts) >= 2:
            rings.append(pts)
    return rings


def lon2x(lon, z):
    return (lon + 180) / 360 * 256 * 2 ** z


def lat2y(lat, z):
    return (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 256 * 2 ** z


def cmd_verify(a):
    ovs = [o for k in (a.kmz or []) for o in read_kmz(k)]
    rings = [r for k in (a.kml or []) for r in read_kml_rings(k)]
    if a.bbox:
        S, W, N, E = floats(a.bbox, 4)
    else:
        bs = [b for _, b in ovs]
        if not bs:
            sys.exit('Cần --kmz hoặc --bbox.')
        S, N = min(b['south'] for b in bs), max(b['north'] for b in bs)
        W, E = min(b['west'] for b in bs), max(b['east'] for b in bs)
        m = 0.04 * max(N - S, E - W)
        S, N, W, E = S - m, N + m, W - m, E + m
    z = a.zoom
    if not z:
        z = 12
        while z < 18 and (lon2x(E, z + 1) - lon2x(W, z + 1)) <= a.max:
            z += 1
    X0, X1, Y0, Y1 = lon2x(W, z), lon2x(E, z), lat2y(N, z), lat2y(S, z)
    tx0, tx1, ty0, ty1 = int(X0 // 256), int(X1 // 256), int(Y0 // 256), int(Y1 // 256)
    jobs = [(x, y) for x in range(tx0, tx1 + 1) for y in range(ty0, ty1 + 1)]
    if len(jobs) > 900:
        sys.exit(f'Quá nhiều tile ({len(jobs)}); giảm --zoom hoặc thu nhỏ --bbox.')
    os.makedirs(a.cache, exist_ok=True)

    def tile(xy):
        x, y = xy
        p = os.path.join(a.cache, f'{z}_{x}_{y}.jpg')
        if not os.path.exists(p):
            with open(p, 'wb') as f:
                f.write(http_get(ESRI.format(z=z, x=x, y=y), timeout=30))
        return p
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(tile, jobs))
    M = Image.new('RGB', ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for x, y in jobs:
        M.paste(Image.open(os.path.join(a.cache, f'{z}_{x}_{y}.jpg')).convert('RGB'), ((x - tx0) * 256, (y - ty0) * 256))
    ox, oy = int(X0 - tx0 * 256), int(Y0 - ty0 * 256)
    M = M.crop((ox, oy, ox + int(X1 - X0), oy + int(Y1 - Y0)))
    base = np.asarray(M, np.float32)
    Hm, Wm = base.shape[:2]
    n = 256 * 2 ** z
    lon = (X0 + np.arange(Wm) + 0.5) / n * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (Y0 + np.arange(Hm) + 0.5) / n))))
    for img, b in ovs:
        ov = np.asarray(img, np.float32)
        oh, ow = ov.shape[:2]
        i = (lon - b['west']) / (b['east'] - b['west']) * ow
        j = (b['north'] - lat) / (b['north'] - b['south']) * oh
        J, I = np.meshgrid(j, i, indexing='ij')
        ok = (I >= 0) & (I < ow) & (J >= 0) & (J < oh)
        px = ov[np.clip(J.astype(int), 0, oh - 1), np.clip(I.astype(int), 0, ow - 1)]
        al = (px[..., 3:4] / 255.0) * a.alpha * ok[..., None]
        base = base * (1 - al) + px[..., :3] * al
    out = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(out)
    for ring in rings:
        d.line([(lon2x(x, z) - X0, lat2y(y, z) - Y0) for x, y in ring], fill=(0, 255, 80), width=3)
    d.rectangle([0, Hm - 16, 150, Hm], fill=(0, 0, 0))
    d.text((4, Hm - 14), 'Imagery (c) Esri', fill=(255, 255, 255))
    out.save(a.out, quality=87)
    print(f'OK {a.out}: {Wm}x{Hm} px, zoom {z} (~{156543.03 * math.cos(math.radians((S + N) / 2)) / 2 ** z:.1f} m/px)')


# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)

    p = sp.add_parser('grid', help='ảnh lưới tọa độ pixel')
    p.add_argument('image')
    p.add_argument('--out', default='grid.jpg')
    p.add_argument('--crop', help='x0,y0,x1,y1 (pixel ảnh gốc) để soi kỹ một vùng')
    p.add_argument('--step', type=int, help='bước lưới (px ảnh gốc)')
    p.add_argument('--max', type=int, default=1600, help='cạnh dài tối đa của ảnh xuất')
    p.add_argument('--exclude', help='vẽ thử các vùng che "x0,y0,x1,y1;..."')
    p.set_defaults(fn=cmd_grid)

    p = sp.add_parser('masks', help='xem phân loại nước/đất sau khi che')
    p.add_argument('image')
    p.add_argument('--exclude', default='')
    p.add_argument('--out', default='masks.png')
    p.add_argument('--sat', type=int, default=45, help='ngưỡng độ bão hòa màu để coi là đất quy hoạch')
    p.add_argument('--max', type=int, default=1400)
    p.set_defaults(fn=cmd_masks)

    p = sp.add_parser('geocode', help='tìm tọa độ + bbox gợi ý theo tên địa danh (Nominatim)')
    p.add_argument('query', help='vd "phường An Khánh, Thành phố Hồ Chí Minh"')
    p.add_argument('--margin-km', type=float, default=3.0, help='nới bbox mỗi phía (km)')
    p.add_argument('--country', default='vn')
    p.set_defaults(fn=cmd_geocode)

    p = sp.add_parser('fetch-osm', help='tải đường + mặt nước OSM')
    p.add_argument('--bbox', required=True, help='S,W,N,E (rộng hơn vùng bản đồ ~2–3 km)')
    p.add_argument('--out', default='osm.json')
    p.set_defaults(fn=cmd_fetch_osm)

    p = sp.add_parser('boundary', help='ranh giới hành chính -> KML')
    p.add_argument('--bbox', required=True, help='S,W,N,E vùng tìm')
    p.add_argument('--name', default='', help='tên phường/xã (không cần dấu), vd "An Khánh"')
    p.add_argument('--id', help='relation id OSM nếu đã biết')
    p.add_argument('--desc', default='', help='mô tả thêm (nghị quyết sắp xếp, thành phần...)')
    p.add_argument('--out', default='ranh_gioi.kml')
    p.set_defaults(fn=cmd_boundary)

    p = sp.add_parser('intersect', help='tọa độ giao lộ 2 đường theo tên')
    p.add_argument('--osm', default='osm.json')
    p.add_argument('--road1', required=True)
    p.add_argument('--road2', required=True)
    p.set_defaults(fn=cmd_intersect)

    p = sp.add_parser('align', help='tự khớp ảnh với OSM')
    p.add_argument('image')
    p.add_argument('--osm', default='osm.json')
    p.add_argument('--exclude', default='', help='vùng che "x0,y0,x1,y1;..." (pixel ảnh gốc)')
    p.add_argument('--scale-range', help='s_min,s_max (pixel/mét); mặc định tự tính theo bbox')
    p.add_argument('--rot-range', default='-3,3', help='độ xoay tìm kiếm (mặc định -3,3)')
    p.add_argument('--gcp', help='điểm khống chế "u,v,lat,lon;..." (>=2, nên 3–5)')
    p.add_argument('--refine', action='store_true', help='với --gcp: tinh chỉnh thêm theo mặt nước')
    p.add_argument('--sat', type=int, default=45)
    p.add_argument('--out', default='params.json')
    p.add_argument('--check', help='ảnh kiểm tra (OSM vẽ đè lên bản đồ)')
    p.add_argument('--boundary', help='KML ranh giới để vẽ kèm trên ảnh kiểm tra')
    p.set_defaults(fn=cmd_align)

    p = sp.add_parser('export', help='xuất KMZ')
    p.add_argument('image', nargs='?', help='mặc định lấy từ params.json')
    p.add_argument('--params', default='params.json')
    p.add_argument('--osm', default='osm.json')
    p.add_argument('--exclude', help='mặc định dùng vùng che đã lưu trong params.json')
    p.add_argument('--name', help='tên lớp trong Google Earth')
    p.add_argument('--desc', help='mô tả: nguồn, số QĐ, ngày công bố... (HTML <br> được)')
    p.add_argument('--color', default='ddffffff', help='aabbggrr; dd = mờ ~13%%')
    p.add_argument('--draw-order', type=int, default=1)
    p.add_argument('--mpp', type=float, help='mét/pixel ảnh xuất (mặc định = độ phân giải gốc)')
    p.add_argument('--keep-river', action='store_true', help='giữ dải sông vẽ trên bản đồ')
    p.add_argument('--out', required=True, help='QHPK<số>_<Khu>_overlay.kmz')
    p.set_defaults(fn=cmd_export)

    p = sp.add_parser('verify', help='ảnh kiểm tra trên nền vệ tinh')
    p.add_argument('--kmz', action='append', help='có thể lặp lại')
    p.add_argument('--kml', action='append', help='KML ranh giới (lặp lại được)')
    p.add_argument('--bbox', help='S,W,N,E; mặc định = phạm vi các lớp phủ')
    p.add_argument('--zoom', type=int, help='mức zoom tile (15 tổng quan, 17 soi chi tiết)')
    p.add_argument('--max', type=int, default=2800, help='bề rộng tối đa khi tự chọn zoom')
    p.add_argument('--alpha', type=float, default=0.55)
    p.add_argument('--cache', default='.tiles')
    p.add_argument('--out', default='kiem_tra_ve_tinh.jpg')
    p.set_defaults(fn=cmd_verify)

    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
