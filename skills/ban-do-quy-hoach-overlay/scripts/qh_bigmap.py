#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "scipy", "shapely>=2.0", "pillow", "pyproj"]
# ///
"""Định vị bản đồ quy hoạch KHỔ LỚN (cấp tỉnh/thành, vùng >50 km) thành KMZ cắt ô.

Tác giả: thieprealtor — https://github.com/thieprealtor/ban-do-quy-hoach-overlay
Giấy phép: MIT (Copyright (c) 2026 thieprealtor) — xem LICENSE.txt

Khác qh_overlay.py (khu vực nhỏ, phép đồng dạng trong hệ mét cục bộ):
  * Hệ tọa độ: UTM (pyproj), gốc dời về tâm bản đồ -> tinh chỉnh tỉ lệ/góc không bị kẹt.
  * Mô hình affine 6 tham số, khớp bằng TRƯỜNG ĐIỂM KHỐNG CHẾ: đo độ lệch cục bộ trên
    nhiều ô có sông/kênh/bờ biển (tương quan FFT), bình phương tối thiểu có loại ngoại lai.
  * --plan-kml: chỉ dùng tín hiệu BÊN TRONG ranh quy hoạch (lớp quy hoạch trên pano hay
    bị đặt lệch so với lớp nền vùng xung quanh hàng trăm mét).
  * register: ghép bản vẽ thứ 2 vào bản vẽ đã định vị qua mặt nước chung (chính xác hơn OSM).
  * export: nắn ảnh gốc độ phân giải đầy đủ sang lưới kinh/vĩ độ bằng lưới MESH, cắt ô
    2048 px, mặt nạ theo ranh (KML), bỏ nước trùng nước thật, chú giải ScreenOverlay.

Lệnh con:
  fetch     Tải mặt nước (lọc ao hồ nhỏ) + đường bờ biển OSM cho bbox lớn -> osm_big.json
  fit       Tìm sơ bộ (FFT) + khớp affine theo trường điểm khống chế -> model.json
  register  Ghép ảnh thứ 2 (cùng bộ bản vẽ) vào model của ảnh thứ nhất -> model2.json
  export    Xuất KMZ cắt ô từ ảnh gốc + model
Ảnh làm việc nên thu nhỏ còn ~5000–7500 px (PIL draft) cho fit/register; export dùng ảnh gốc
với --scale = (cạnh ảnh gốc / cạnh ảnh làm việc).
"""
import argparse, io, json, math, os, sys, time, zipfile
from xml.dom import minidom
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, signal
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union, polygonize
from shapely.prepared import prep
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qh_overlay as q  # noqa: E402

Image.MAX_IMAGE_PIXELS = None


# ------------------------------------------------------------------ hệ tọa độ
class UTMFrame:
    """x = Easting - E0, y = -(Northing - N0): gốc ở tâm bản đồ, y hướng Nam như hàng ảnh."""
    def __init__(self, lat0, lon0, epsg=None):
        zone = int((lon0 + 180) // 6) + 1
        self.epsg = epsg or (32600 + zone if lat0 >= 0 else 32700 + zone)
        self.lat0, self.lon0 = lat0, lon0
        self._f = Transformer.from_crs('EPSG:4326', f'EPSG:{self.epsg}', always_xy=True)
        self._i = Transformer.from_crs(f'EPSG:{self.epsg}', 'EPSG:4326', always_xy=True)
        self.E0, self.N0 = self._f.transform(lon0, lat0)
    def fwd(self, lon, lat):
        x, y = self._f.transform(np.asarray(lon, float), np.asarray(lat, float))
        return np.asarray(x) - self.E0, -(np.asarray(y) - self.N0)
    def inv(self, x, y):
        return self._i.transform(np.asarray(x, float) + self.E0, self.N0 - np.asarray(y, float))
    def geom(self, g):
        from shapely.ops import transform
        return transform(lambda x, y, z=None: self.fwd(x, y), g)


def w2p(tf, x, y):
    a, b, c, d, xo, yo = tf
    return a * x + b * y + xo, c * x + d * y + yo


def p2w(tf, u, v):
    a, b, c, d, xo, yo = tf
    det = a * d - b * c
    du, dv = np.asarray(u) - xo, np.asarray(v) - yo
    return (d * du - b * dv) / det, (-c * du + a * dv) / det


# ------------------------------------------------------------------ dữ liệu
def masks(img, exclude, sat=45):
    """Nước: xanh lơ (g-r>35, b-g>12, b>150) — không nhầm khu công nghiệp tím; đất: màu bão hòa."""
    a = np.asarray(img.convert('RGB')).astype(np.int16)
    H, W, _ = a.shape
    valid = np.ones((H, W), bool)
    for x0, y0, x1, y1 in exclude:
        valid[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    water = (b > 150) & (g - r > 35) & (b - g > 12) & valid
    land = ((a.max(-1) - a.min(-1)) > sat) & ~water & valid
    return water, land


def sea_polygon(coast_ways, bb, sea_pts):
    S, W, N, E = bb
    frame = box(W, S, E, N)
    lines = [LineString([(p['lon'], p['lat']) for p in e['geometry']]) for e in coast_ways if len(e.get('geometry', [])) >= 2]
    faces = list(polygonize(unary_union([ln.intersection(frame) for ln in lines] + [frame.exterior])))
    sea = [f for f in faces if any(f.contains(Point(lo, la)) for la, lo in sea_pts)]
    return unary_union(sea) if sea else None


def load_water(path, min_km2=0.02):
    d = json.load(open(path))
    water = q.load_osm(d)[0]
    S, W, N, E = d['bbox']
    fr = UTMFrame((S + N) / 2, (W + E) / 2)
    keep = [p for p in q.polys(water) if fr.geom(p).area >= min_km2 * 1e6]
    if d.get('sea_wkt'):
        from shapely import wkt
        keep.append(wkt.loads(d['sea_wkt']))
    return unary_union(keep), d['bbox']


def read_kml_polygon(path):
    rings = q.read_kml_rings(path)
    return unary_union([Polygon(r).buffer(0) for r in rings if len(r) >= 4])


# ------------------------------------------------------------------ fetch
def cmd_fetch(a):
    S, W, N, E = q.floats(a.bbox, 4)
    bb = f'{S},{W},{N},{E}'
    filt = '["water"!~"^(pond|basin|wastewater|fish_pond|fishpond|aquaculture|reflecting_pool|swimming_pool|moat|ditch|drain)$"]'
    d = q.overpass(f'[out:json][timeout:300];(way["natural"="water"]{filt}({bb});relation["natural"="water"]({bb});'
                   f'way["waterway"="riverbank"]({bb});relation["waterway"="riverbank"]({bb}););out geom;')
    d['bbox'] = [S, W, N, E]
    if a.sea_point:
        c = q.overpass(f'[out:json][timeout:180];way["natural"="coastline"]({bb});out geom;')
        pts = [tuple(q.floats(p, 2)) for p in a.sea_point.split(';')]
        sea = sea_polygon(c['elements'], (S, W, N, E), pts)
        if sea is None:
            print('  Cảnh báo: không dựng được mặt biển (kiểm tra --sea-point nằm ngoài khơi trong bbox).')
        else:
            d['sea_wkt'] = sea.wkt
    json.dump(d, open(a.out, 'w'))
    print(f'OK {a.out}: {len(d["elements"])} đối tượng nước' + (', có mặt biển' if d.get('sea_wkt') else ''))


# ------------------------------------------------------------------ đo trường điểm khống chế
def gcp_field(water, land, O, win, step, R, min_water=300):
    H, W = water.shape
    Wm, Lm = water.astype(np.float32), land.astype(np.float32)
    Op = np.pad(O, R)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    out = []
    for v0 in range(0, H - win + 1, step):
        for u0 in range(0, W - win + 1, step):
            w, l = Wm[v0:v0 + win, u0:u0 + win], Lm[v0:v0 + win, u0:u0 + win]
            nw, nl = w.sum(), l.sum()
            if nw < min_water or nw > 0.35 * win * win or nl < 2000:
                continue
            C = signal.fftconvolve(Op[v0:v0 + win + 2 * R, u0:u0 + win + 2 * R], (w / nw - l / nl)[::-1, ::-1], mode='valid')
            iy, ix = np.unravel_index(np.argmax(C), C.shape)
            if iy in (0, 2 * R) or ix in (0, 2 * R):
                continue
            def sp(c, i):
                dd = c[i - 1] - 2 * c[i] + c[i + 1]
                return i + (0.5 * (c[i - 1] - c[i + 1]) / dd if dd < 0 else 0.0)
            dx, dy = -(sp(C[iy, :], ix) - R), -(sp(C[:, ix], iy) - R)
            ring = C[np.hypot(yy - (iy - R), xx - (ix - R)) > 6]
            sharp = (C.max() - np.median(ring)) / (ring.std() + 1e-9)
            ys, xs = np.nonzero(w)
            out.append((u0 + xs.mean() + 0.5, v0 + ys.mean() + 0.5, dx, dy, sharp))
    return np.array(out).reshape(-1, 5)


def fit_affine(X, Y, U, V):
    keep = np.ones(len(X), bool)
    for _ in range(8):
        n = keep.sum(); o = np.ones(n); z = np.zeros(n)
        A = np.block([[X[keep, None], Y[keep, None], z[:, None], z[:, None], o[:, None], z[:, None]],
                      [z[:, None], z[:, None], X[keep, None], Y[keep, None], z[:, None], o[:, None]]])
        p, *_ = np.linalg.lstsq(A, np.concatenate([U[keep], V[keep]]), rcond=None)
        a, b, c, d, xo, yo = p
        r = np.hypot(a * X + b * Y + xo - U, c * X + d * Y + yo - V)
        new = r <= max(3 * 1.4826 * np.median(r[keep]), 1.0)
        if (new == keep).all():
            break
        keep = new
    return [float(v) for v in (a, b, c, d, xo, yo)], r, keep


def iterate_gcps(fr, WL, water, land, tf, plan=None, iters=3, win=360, step=120, R=16, min_sharp=5.0, log=''):
    H, W = water.shape
    for it in range(iters):
        O = q.raster([q.affine_transform(WL, tf).intersection(box(-50, -50, W + 50, H + 50))], (W, H))
        wm, lm = water, land
        if plan is not None:
            PA = q.raster([q.affine_transform(fr.geom(plan), tf)], (W, H)) > 0
            wm, lm = water & PA, land & PA
        g = gcp_field(wm, lm, O, win, step, R)
        g = g[g[:, 4] >= min_sharp]
        if len(g) < 6:
            print(f'  {log}quá ít điểm khống chế ({len(g)}) -> giữ kết quả trước đó (khung đảo/ít sông: bình thường).')
            return tf, None
        X, Y = p2w(tf, g[:, 0], g[:, 1])
        tf, r, keep = fit_affine(X, Y, g[:, 0] + g[:, 2], g[:, 1] + g[:, 3])
        mpp = 1 / math.sqrt(abs(tf[0] * tf[3] - tf[1] * tf[2]))
        print(f'  {log}vòng {it + 1}: {len(g)} điểm, giữ {keep.sum()} | lệch trung vị {np.median(r[keep]) * mpp:.0f} m, '
              f'p90 {np.quantile(r[keep], .9) * mpp:.0f} m (tất cả: p90 {np.quantile(r, .9) * mpp:.0f} m)', flush=True)
    return tf, dict(n=int(len(g)), kept=int(keep.sum()), median_m=float(np.median(r[keep]) * mpp),
                    p90_m=float(np.quantile(r[keep], .9) * mpp), mpp=float(mpp))


# ------------------------------------------------------------------ fit
def cmd_fit(a):
    water_ll, bb = load_water(a.osm)
    S, W_, N, E = bb
    lat0, lon0 = ((S + N) / 2, (W_ + E) / 2) if not a.center else q.floats(a.center, 2)
    fr = UTMFrame(lat0, lon0)
    WL = fr.geom(water_ll).simplify(a.simplify)
    ex = q.rects(a.exclude)
    img = Image.open(a.image)
    water, land = masks(img, ex, a.sat)
    H, W = water.shape
    # 1) tìm sơ bộ bằng FFT (dùng lại Aligner của qh_overlay với hệ UTM)
    al = q.Aligner.__new__(q.Aligner)
    al.fr, al.WL, al.water, al.land, al.H, al.W = fr, WL, water, land, H, W
    xs, ys = fr.fwd([W_, E, W_, E], [S, S, N, N])
    al.xmin, al.xmax, al.ymin, al.ymax = float(min(xs)), float(max(xs)), float(min(ys)), float(max(ys))
    if a.scale_range:
        s_lo, s_hi = q.floats(a.scale_range, 2)
    else:
        diag = math.hypot(al.xmax - al.xmin, al.ymax - al.ymin)
        s_lo, s_hi = max(H, W) / diag, max(H, W) / (0.25 * diag)
    r0, r1 = q.floats(a.rot_range, 2)
    t = time.time()
    sc, P = al.search(s_lo, s_hi, list(np.arange(r0, r1 + 1e-9, 1.0)))
    sc, P = al.refine(P)
    print(f'Sơ bộ: score {sc:.3f}, {1 / P["s"]:.1f} m/px, xoay {P["rot"]:.2f}° ({time.time() - t:.0f}s)')
    s, r = P['s'], math.radians(P['rot'])
    tf = [s * math.cos(r), -s * math.sin(r), s * math.sin(r), s * math.cos(r), P['cx'], P['cy']]
    # 2) trường điểm khống chế + affine (toàn ảnh), rồi chỉ trong ranh quy hoạch nếu có
    st0 = dict(n=0, kept=0, median_m=float('nan'), p90_m=float('nan'), mpp=float(1 / P['s']), coarse_score=float(sc))
    tf, st = iterate_gcps(fr, WL, water, land, tf, iters=3, win=a.win, step=a.win // 3, R=24, log='[toàn ảnh] ')
    st = st or st0
    plan = None
    if a.plan_kml:
        plan = read_kml_polygon(a.plan_kml).buffer(-a.plan_shrink)
        tf, st2 = iterate_gcps(fr, WL, water, land, tf, plan=plan, iters=3, win=a.win, step=a.win // 3, R=24, log='[trong ranh QH] ')
        st = st2 or st
    sx, sy = math.hypot(tf[0], tf[2]), math.hypot(tf[1], tf[3])
    out = dict(epsg=fr.epsg, lat0=lat0, lon0=lon0, tf=tf, image=os.path.abspath(a.image), image_size=[W, H],
               exclude=ex, stats=st, aniso=sy / sx, rot_deg=math.degrees(math.atan2(tf[2], tf[0])))
    json.dump(out, open(a.out, 'w'), indent=1)
    print(f'OK {a.out}: {st["mpp"]:.1f} m/px, lệch trung vị {st["median_m"]:.0f} m, p90 {st["p90_m"]:.0f} m, '
          f'xoay {out["rot_deg"]:.3f}°, dọc/ngang {out["aniso"]:.4f}')
    if a.check:
        im = img.convert('RGB'); k = min(1.0, 1800 / max(W, H)); im = im.resize((int(W * k), int(H * k)))
        d = ImageDraw.Draw(im)
        for p in q.polys(q.affine_transform(WL, tf).intersection(box(0, 0, W, H))):
            d.line([(x * k, y * k) for x, y in p.exterior.coords], fill=(255, 0, 255), width=1)
        if plan is not None:
            for p in q.polys(q.affine_transform(fr.geom(plan), tf)):
                d.line([(x * k, y * k) for x, y in p.exterior.coords], fill=(0, 0, 0), width=2)
        im.save(a.check, quality=85)
        print(f'  Ảnh kiểm tra: {a.check} (tím = mép nước OSM)')


# ------------------------------------------------------------------ register
def cmd_register(a):
    M = json.load(open(a.model))
    w1, _ = masks(Image.open(M['image']), [tuple(r) for r in M['exclude']])
    w2, _ = masks(Image.open(a.image), q.rects(a.exclude))
    fr = UTMFrame(M['lat0'], M['lon0'], M['epsg'])
    H, W = w1.shape
    A = w1.astype(np.float32)
    if a.plan_kml:
        plan = read_kml_polygon(a.plan_kml).buffer(-a.plan_shrink)
        A *= q.raster([q.affine_transform(fr.geom(plan), M['tf'])], (W, H)) > 0
    R, win, step = a.radius, 400, 160
    P2 = np.pad(w2.astype(np.float32), R)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    pairs = []
    for v0 in range(0, H - win + 1, step):
        for u0 in range(0, W - win + 1, step):
            w = A[v0:v0 + win, u0:u0 + win]; nw = w.sum()
            if nw < 400 or nw > 0.35 * win * win:
                continue
            C = signal.fftconvolve(P2[v0:v0 + win + 2 * R, u0:u0 + win + 2 * R], (w - w.mean())[::-1, ::-1], mode='valid')
            iy, ix = np.unravel_index(np.argmax(C), C.shape)
            if iy in (0, 2 * R) or ix in (0, 2 * R):
                continue
            ring = C[np.hypot(yy - (iy - R), xx - (ix - R)) > 5]
            if (C.max() - np.median(ring)) / (ring.std() + 1e-9) < 6:
                continue
            def sp(c, i):
                dd = c[i - 1] - 2 * c[i] + c[i + 1]
                return i + (0.5 * (c[i - 1] - c[i + 1]) / dd if dd < 0 else 0.0)
            ys, xs = np.nonzero(w); u, v = u0 + xs.mean() + 0.5, v0 + ys.mean() + 0.5
            pairs.append((u, v, u + sp(C[iy, :], ix) - R, v + sp(C[:, ix], iy) - R))
    Pp = np.array(pairs)
    if len(Pp) < 6:
        sys.exit('Quá ít vùng nước chung để ghép.')
    rel, r, keep = fit_affine(Pp[:, 0], Pp[:, 1], Pp[:, 2], Pp[:, 3])
    ra, rb, rc, rd, rxo, ryo = rel
    a1, b1, c1, d1, x1, y1 = M['tf']
    tf2 = [ra * a1 + rb * c1, ra * b1 + rb * d1, rc * a1 + rd * c1, rc * b1 + rd * d1, ra * x1 + rb * y1 + rxo, rc * x1 + rd * y1 + ryo]
    out = dict(M, tf=tf2, image=os.path.abspath(a.image), exclude=q.rects(a.exclude), registered_to=a.model,
               register_stats=dict(n=int(len(Pp)), kept=int(keep.sum()), median_px=float(np.median(r[keep]))))
    json.dump(out, open(a.out, 'w'), indent=1)
    print(f'OK {a.out}: {len(Pp)} vùng, giữ {keep.sum()}, lệch ghép trung vị {np.median(r[keep]):.2f} px; '
          f'dịch chuyển trung bình so với bản 1: ({np.median(Pp[:, 2] - Pp[:, 0]):+.1f}, {np.median(Pp[:, 3] - Pp[:, 1]):+.1f}) px')


# ------------------------------------------------------------------ export
def poly_mask(geom, west, north, dlon, dlat, W, H):
    img = Image.new('L', (W, H), 0)
    if not geom.is_empty:
        d = ImageDraw.Draw(img)
        f = lambda cs: [((x - west) / dlon, (north - y) / dlat) for x, y in cs]
        ps = q.polys(geom)
        for p in ps:
            d.polygon(f(p.exterior.coords), fill=1)
        for p in ps:
            for it in p.interiors:
                d.polygon(f(it.coords), fill=0)
    return np.asarray(img, bool)


def cmd_export(a):
    M = json.load(open(a.model))
    fr = UTMFrame(M['lat0'], M['lon0'], M['epsg'])
    tf = [v * a.scale for v in M['tf']]
    src = Image.open(a.image); src.load(); src = src.convert('RGBA')
    clip = read_kml_polygon(a.clip_kml).buffer(a.clip_buffer)
    if a.exclude_world:   # vùng trên bản vẽ (pixel ảnh LÀM VIỆC) không thuộc lớp chính, vd khung Côn Đảo
        for x0, y0, x1, y1 in q.rects(a.exclude_world):
            xs, ys = p2w(M['tf'], np.array([x0, x1, x1, x0]), np.array([y0, y0, y1, y1]))
            lo, la = fr.inv(xs, ys)
            clip = clip.difference(Polygon(list(zip(lo, la))).buffer(0.01))
    water_ll = load_water(a.osm)[0] if a.osm else None
    west, south, east, north = clip.bounds
    mpp = a.mpp or 1 / math.sqrt(abs(tf[0] * tf[3] - tf[1] * tf[2]))
    dlon, dlat = mpp / (111320 * math.cos(math.radians((south + north) / 2))), mpp / 110574
    Wpx, Hpx = int(math.ceil((east - west) / dlon)), int(math.ceil((north - south) / dlat))
    files, tiles, T, CELL = {}, [], a.tile, 64
    for ty in range(0, Hpx, T):
        for tx in range(0, Wpx, T):
            w, h = min(T, Wpx - tx), min(T, Hpx - ty)
            tw, tn = west + tx * dlon, north - ty * dlat
            tb = box(tw, tn - h * dlat, tw + w * dlon, tn)
            ct = clip.intersection(tb)
            if ct.is_empty:
                continue
            xs = np.unique(np.arange(0, w + CELL, CELL).clip(max=w)); ys = np.unique(np.arange(0, h + CELL, CELL).clip(max=h))
            LON, LAT = np.meshgrid(tw + xs * dlon, tn - ys * dlat)
            U, V = w2p(tf, *fr.fwd(LON, LAT))
            mesh = [((int(xs[i]), int(ys[j]), int(xs[i + 1]), int(ys[j + 1])),
                     (U[j, i], V[j, i], U[j + 1, i], V[j + 1, i], U[j + 1, i + 1], V[j + 1, i + 1], U[j, i + 1], V[j, i + 1]))
                    for j in range(len(ys) - 1) for i in range(len(xs) - 1)]
            arr = np.asarray(src.transform((w, h), Image.MESH, mesh, resample=Image.BILINEAR)).copy()
            rgb = arr[..., :3].astype(np.int16); mx, mn = rgb.max(-1), rgb.min(-1)
            keep = (arr[..., 3] > 0) & poly_mask(ct, tw, tn, dlon, dlat, w, h)
            keep &= ~(mn > 238) & ~((mn > 225) & (mx - mn < 28))          # trắng / nền nhạt
            if a.drop_gray:
                keep &= ~((mx - mn <= 10) & (mn >= 195))                   # xám trung tính
            if water_ll is not None:
                osmw = ndimage.binary_dilation(poly_mask(water_ll.intersection(tb.buffer(0.01)), tw, tn, dlon, dlat, w, h), iterations=3)
                r_, g_, b_ = rgb[..., 0], rgb[..., 1], rgb[..., 2]
                keep &= ~(((b_ > 150) & (g_ - r_ > 35) & (b_ - g_ > 12)) & osmw)
            if keep.sum() < 50:
                continue
            arr[..., 3] = np.where(keep, 255, 0).astype(np.uint8)
            buf = io.BytesIO()
            Image.fromarray(arr, 'RGBA').quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(buf, 'PNG', optimize=True)
            name = f'files/{a.tag}_r{ty // T}_c{tx // T}.png'
            files[name] = buf.getvalue(); tiles.append((name, tn, tn - h * dlat, tw + w * dlon, tw))
    legend = ''
    if a.legend:
        x0, y0, x1, y1 = [int(v * a.scale) for v in q.floats(a.legend, 4)]
        lg = src.crop((x0, y0, x1, y1)).convert('RGB'); lg.thumbnail((900, 1800), Image.LANCZOS)
        buf = io.BytesIO(); lg.save(buf, 'PNG', optimize=True); files['files/chu_giai.png'] = buf.getvalue()
        legend = ('<ScreenOverlay><name>Chú giải (kí hiệu)</name><Icon><href>files/chu_giai.png</href></Icon>'
                  '<overlayXY x="0" y="0" xunits="fraction" yunits="fraction"/><screenXY x="0.005" y="0.04" xunits="fraction" yunits="fraction"/>'
                  '<size x="0" y="0.62" xunits="fraction" yunits="fraction"/></ScreenOverlay>')
    st = M.get('stats', {})
    med, p90 = st.get('median_m', float('nan')), st.get('p90_m', float('nan'))
    acc = (f'lệch trung vị ~{med:.0f} m, 90% điểm dưới ~{p90:.0f} m' if med == med else 'khớp theo đường bờ/mặt nước, sai số ~1–2 điểm ảnh')
    desc = (a.desc or '') + ('<br>' if a.desc else '') + (
        f'Định vị: khớp theo sông, kênh, bờ biển OpenStreetMap (UTM + affine); {acc}; '
        f'độ phân giải ~{mpp:.0f} m/điểm ảnh. Chỉ để tham khảo; đối chiếu thông tin quy hoạch chính thức.'
        + ('<br><img src="files/chu_giai.png" width="420"/>' if a.legend else ''))
    go = lambda t: (f'<GroundOverlay><name>{t[0]}</name><color>{a.color}</color><drawOrder>{a.draw_order}</drawOrder><Icon><href>{t[0]}</href></Icon>'
                    f'<LatLonBox><north>{t[1]:.7f}</north><south>{t[2]:.7f}</south><east>{t[3]:.7f}</east><west>{t[4]:.7f}</west></LatLonBox></GroundOverlay>')
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f'<name>{a.name}</name><open>1</open><description><![CDATA[{desc}]]></description>'
           f'<Folder><name>{a.name} ({len(tiles)} ô ảnh)</name>' + ''.join(go(t) for t in tiles) + '</Folder>' + legend + '</Document></kml>\n')
    minidom.parseString(kml.encode('utf-8'))
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_STORED) as z:
        z.writestr('doc.kml', kml.encode('utf-8'))
        for k, v in files.items():
            z.writestr(k, v)
    print(f'OK {a.out}: {len(tiles)} ô ảnh, lưới {Wpx}x{Hpx}, {mpp:.1f} m/px, {os.path.getsize(a.out) / 1e6:.1f} MB')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    p = sp.add_parser('fetch', help='mặt nước + bờ biển OSM cho bbox lớn')
    p.add_argument('--bbox', required=True, help='S,W,N,E phủ CẢ tờ bản đồ (kể cả vùng xung quanh)')
    p.add_argument('--sea-point', help='"lat,lon;..." điểm ngoài khơi trong bbox để dựng mặt biển từ đường bờ')
    p.add_argument('--out', default='osm_big.json'); p.set_defaults(fn=cmd_fetch)

    p = sp.add_parser('fit', help='khớp affine theo trường điểm khống chế')
    p.add_argument('image', help='ảnh LÀM VIỆC đã thu nhỏ (~5000–7500 px)')
    p.add_argument('--osm', default='osm_big.json'); p.add_argument('--exclude', default='')
    p.add_argument('--plan-kml', help='ranh quy hoạch (KML) để chỉ dùng tín hiệu trong ranh')
    p.add_argument('--plan-shrink', type=float, default=0.002, help='lùi vào trong ranh (độ, ~0.002 = 200 m)')
    p.add_argument('--center', help='lat,lon tâm hệ tọa độ (mặc định tâm bbox)')
    p.add_argument('--scale-range', help='s_min,s_max px/m cho ảnh làm việc')
    p.add_argument('--rot-range', default='-3,3', help='dạng --rot-range=-6,6'); p.add_argument('--sat', type=int, default=45)
    p.add_argument('--simplify', type=float, default=8.0)
    p.add_argument('--win', type=int, default=360, help='cỡ ô đo (px); ảnh nhỏ như khung đảo: 160–200')
    p.add_argument('--out', default='model.json'); p.add_argument('--check'); p.set_defaults(fn=cmd_fit)

    p = sp.add_parser('register', help='ghép bản vẽ thứ 2 vào model bản 1')
    p.add_argument('image'); p.add_argument('--model', required=True); p.add_argument('--exclude', default='')
    p.add_argument('--plan-kml'); p.add_argument('--plan-shrink', type=float, default=0.01)
    p.add_argument('--radius', type=int, default=40, help='bán kính tìm (px ảnh làm việc)')
    p.add_argument('--out', default='model2.json'); p.set_defaults(fn=cmd_register)

    p = sp.add_parser('export', help='xuất KMZ cắt ô')
    p.add_argument('image', help='ảnh GỐC độ phân giải đầy đủ'); p.add_argument('--model', required=True)
    p.add_argument('--scale', type=float, required=True, help='cạnh ảnh gốc / cạnh ảnh làm việc')
    p.add_argument('--clip-kml', required=True, help='ranh hiển thị (KML)')
    p.add_argument('--clip-buffer', type=float, default=0.0015)
    p.add_argument('--exclude-world', help='khung trên bản vẽ (px ảnh làm việc) không thuộc lớp chính')
    p.add_argument('--osm', help='osm_big.json để bỏ nước vẽ trùng nước thật')
    p.add_argument('--drop-gray', action='store_true', help='làm trong suốt vùng xám trung tính')
    p.add_argument('--legend', help='x0,y0,x1,y1 khung chú giải (px ảnh làm việc)')
    p.add_argument('--name', default='Lớp phủ quy hoạch'); p.add_argument('--desc', default='')
    p.add_argument('--tag', default='qh'); p.add_argument('--tile', type=int, default=2048)
    p.add_argument('--mpp', type=float); p.add_argument('--color', default='ddffffff')
    p.add_argument('--draw-order', type=int, default=2)
    p.add_argument('--out', required=True); p.set_defaults(fn=cmd_export)
    a = ap.parse_args(); a.fn(a)


if __name__ == '__main__':
    main()
