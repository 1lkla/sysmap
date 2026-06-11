"""sysmap crawler — read-only reconnaissance of a logged-in web app via browser-harness.

Run with:   SYSMAP_URL=... browser-harness < sysmap_crawl.py

Env:
  SYSMAP_URL        target start URL (required)
  SYSMAP_MAX_PAGES  max routes to visit (default 40)
  SYSMAP_OUT        output dir (default ./sysmap-out)

Writes graphify-ready markdown into $SYSMAP_OUT/raw/ plus a raw network.jsonl.
Helpers (new_tab, cdp, js, drain_events, wait_for_load, page_info) are pre-imported
by the browser-harness runtime. This script is intentionally READ-ONLY: it only
navigates (GET) and reads the DOM. It never clicks state-changing controls.
"""
import os, json, time, re
from urllib.parse import urlparse, urldefrag, urljoin

START = os.environ.get("SYSMAP_URL")
assert START, "set SYSMAP_URL=<start url>"
MAX_PAGES = int(os.environ.get("SYSMAP_MAX_PAGES", "40"))
OUT = os.environ.get("SYSMAP_OUT", "./sysmap-out")
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)

_pu = urlparse(START)
ORIGIN = "%s://%s" % (_pu.scheme, _pu.netloc)
SYSTEM = _pu.netloc

ADMIN_HINTS = ("admin", "manage", "console", "setting", "config", "permission",
               "role", "audit", "system", "operator", "backstage", "后台", "管理")
FILE_HINTS = ("upload", "download", "import", "export", "attach", "csv", "excel",
               "xlsx", "pdf", "report", "文件", "导入", "导出", "上传", "下载")
PERM_WORDS = ("forbidden", "unauthorized", "permission denied", "access denied",
              "not allowed", "403", "无权限", "未授权", "权限不足", "禁止访问")

try:
    from browser_harness.helpers import _send
except Exception:
    _send = None

def norm(u):
    u, _ = urldefrag(u or "")
    return u.rstrip("/")

def same_origin(u):
    try:
        return urlparse(u).netloc == _pu.netloc
    except Exception:
        return False

def api_key(method, url):
    p = urlparse(url)
    path = re.sub(r"/\d+", "/{id}", p.path) or "/"
    path = re.sub(r"/[0-9a-f]{8,}", "/{id}", path)
    return "%s %s" % (method.upper(), path)

# --- network capture: mirrors wait_for_network_idle but KEEPS the events ---
def capture_until_idle(timeout=12.0, idle_ms=700):
    deadline = time.time() + timeout
    last = time.time()
    inflight = set()
    reqs, resp = {}, {}
    active = None
    if _send:
        try:
            active = _send({"meta": "session"}).get("session_id")
        except Exception:
            active = None
    while time.time() < deadline:
        for e in drain_events():
            if active and e.get("session_id") != active:
                continue
            m = e.get("method", "")
            p = e.get("params", {})
            if m == "Network.requestWillBeSent":
                rid = p.get("requestId")
                r = p.get("request", {})
                reqs[rid] = {"url": r.get("url", ""), "method": r.get("method", ""),
                             "type": p.get("type", ""), "postData": (r.get("postData") or "")[:300]}
                inflight.add(rid); last = time.time()
            elif m == "Network.responseReceived":
                rid = p.get("requestId")
                rr = p.get("response", {})
                resp[rid] = {"status": rr.get("status"), "mime": rr.get("mimeType", "")}
                last = time.time()
            elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                inflight.discard(p.get("requestId")); last = time.time()
        if not inflight and (time.time() - last) * 1000 >= idle_ms:
            break
        time.sleep(0.1)
    out = []
    for rid, r in reqs.items():
        rec = dict(r); rec.update(resp.get(rid, {}))
        out.append(rec)
    return out

EXTRACT_JS = r"""
(function () {
  var T = function (el) {
    return ((el.innerText || el.textContent || el.value ||
             el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim().slice(0, 80);
  };
  var A = function (h) { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
  var sel = function (q) { return Array.prototype.slice.call(document.querySelectorAll(q)); };
  var links = sel('a[href]').map(function (a) {
    return { href: A(a.getAttribute('href')), text: T(a) };
  }).filter(function (l) { return l.href; });
  var buttons = sel('button,[role=button],input[type=submit],input[type=button]').map(function (b) {
    return { text: T(b), disabled: !!(b.disabled || b.getAttribute('aria-disabled') === 'true') };
  }).filter(function (b) { return b.text; });
  var forms = sel('form').map(function (f) {
    return { action: A(f.getAttribute('action') || ''), method: (f.getAttribute('method') || 'get'),
      inputs: Array.prototype.slice.call(f.querySelectorAll('input,select,textarea'))
        .map(function (i) { return i.name || i.type; }).filter(Boolean).slice(0, 20),
      hasFile: !!f.querySelector('input[type=file]') };
  });
  var fileInputs = sel('input[type=file]').map(function (i) {
    return { name: i.name || '', accept: i.accept || '' };
  });
  var downloads = sel('a[download],a[href$=".csv"],a[href$=".pdf"],a[href$=".xlsx"],a[href$=".xls"],a[href$=".zip"]')
    .map(function (a) { return { href: A(a.getAttribute('href') || ''), text: T(a) }; });
  var nav = sel('nav a[href], [role=navigation] a[href], aside a[href], .menu a[href], .sidebar a[href], .ant-menu a[href], .el-menu a[href]')
    .map(function (a) { return { href: A(a.getAttribute('href')), text: T(a) }; }).filter(function (l) { return l.href; });
  var headings = sel('h1,h2').map(T).filter(Boolean).slice(0, 12);
  var bodyText = (document.body ? (document.body.innerText || '') : '').slice(0, 600);
  return JSON.stringify({ title: document.title, url: location.href, links: links,
    buttons: buttons, forms: forms, fileInputs: fileInputs, downloads: downloads,
    nav: nav, headings: headings, bodyText: bodyText });
})()
"""

def is_admin(url, title, headings):
    blob = (url + " " + (title or "") + " " + " ".join(headings or [])).lower()
    return any(h in blob for h in ADMIN_HINTS)

# --- static JS harvest: routes + API endpoints hidden in webpack/SPA bundles ---
# Modern SPAs declare their router table and fetch/axios endpoints inside JS
# bundles, not in server-rendered <a href>. We download every same-origin script
# and statically mine route paths + /api/ endpoints (with HTTP method when the
# call site reveals it). This is still read-only — we only GET static assets.
JS_SRCS = "(function(){return JSON.stringify(Array.prototype.slice.call(document.scripts).map(function(s){return s.src;}).filter(Boolean));})()"
API_RE = re.compile(r"""['"`](/api/[A-Za-z0-9_\-./{}]+)['"`]""")
PATH_RE = re.compile(r"""path\s*:\s*['"](/[A-Za-z0-9_\-./:]*)['"]""")
METHOD_CALL_RE = re.compile(r"""\.(get|post|put|delete|patch)\s*\(\s*['"`](/api/[A-Za-z0-9_\-./{}]+)""", re.I)
METHOD_OBJ_RE = re.compile(
    r"""url\s*:\s*['"`](/api/[A-Za-z0-9_\-./{}]+)['"`][^{}]{0,80}?method\s*:\s*['"`](\w+)"""
    r"""|method\s*:\s*['"`](\w+)['"`][^{}]{0,80}?url\s*:\s*['"`](/api/[A-Za-z0-9_\-./{}]+)['"`]""",
    re.I)

def harvest_js():
    """Return (api_methods{path:set(METHOD)}, route_paths[list], n_scripts_fetched)."""
    try:
        raw = js(JS_SRCS)
        srcs = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        srcs = []
    srcs = [s for s in srcs if same_origin(s)]
    blobs = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        def _g(u):
            try:
                return http_get(u) or ""
            except Exception:
                return ""
        with ThreadPoolExecutor(max_workers=16) as ex:
            blobs = list(ex.map(_g, srcs))
    except Exception:
        for u in srcs:
            try:
                blobs.append(http_get(u) or "")
            except Exception:
                pass
    blob = "\n".join(blobs)
    methods = {}
    for m in METHOD_CALL_RE.finditer(blob):
        methods.setdefault(m.group(2).rstrip("."), set()).add(m.group(1).upper())
    for m in METHOD_OBJ_RE.finditer(blob):
        p = (m.group(1) or m.group(4) or "").rstrip(".")
        meth = (m.group(2) or m.group(3) or "").upper()
        if p:
            methods.setdefault(p, set()).add(meth)
    api_methods = {}
    for m in API_RE.finditer(blob):
        p = m.group(1).rstrip(".")
        api_methods.setdefault(p, set()).update(methods.get(p, set()))
    routes_found = sorted({m.group(1) for m in PATH_RE.finditer(blob)
                           if not m.group(1).startswith("/api")})
    return api_methods, routes_found, len(blobs)

# ---- crawl ----
print("sysmap: crawling %s (origin %s, max %d pages)" % (START, ORIGIN, MAX_PAGES))
new_tab(START); wait_for_load()
cdp("Network.enable")

seen, queue, routes = set(), [norm(START)], []
apis = {}          # key -> {methods, statuses, types, routes, full_url, is_file, sources}

# --- harvest JS first: seed routes + register statically-known APIs ---
js_apis, js_routes, n_js = harvest_js()
print("sysmap: harvested %d JS bundles -> %d route paths, %d API endpoints" %
      (n_js, len(js_routes), len(js_apis)))
for rp in js_routes:
    full = norm(ORIGIN + rp)
    if full not in queue:
        queue.append(full)
for p, meths in sorted(js_apis.items()):
    norm_path = re.sub(r"/\d+", "/{id}", p)
    for meth in (sorted(m for m in meths if m) or ["?"]):
        k = "%s %s" % (meth, norm_path)
        slot = apis.setdefault(k, {"methods": set(), "statuses": set(), "types": set(),
                                   "routes": set(), "full_url": ORIGIN + p, "is_file": False,
                                   "sources": set()})
        if meth != "?":
            slot["methods"].add(meth)
        slot["is_file"] = slot["is_file"] or any(h in p.lower() for h in FILE_HINTS)
        slot["sources"].add("JS-static")
file_ctrls = []    # {route, kind, label}
perm_signals = []  # {route, kind, detail}
admin_routes = []
network_log = []

while queue and len(routes) < MAX_PAGES:
    url = queue.pop(0)
    if url in seen or not url:
        continue
    seen.add(url)
    try:
        drain_events()
        cdp("Page.navigate", url=url)
        recs = capture_until_idle()
        wait_for_load()
        raw = js(EXTRACT_JS)
        data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception as ex:
        print("  ! skip %s (%s)" % (url, ex))
        continue

    cur = norm(data.get("url") or url)
    title = data.get("title", "")
    headings = data.get("headings", [])
    admin = is_admin(cur, title, headings)
    print("  + %s  %s%s" % (cur, (title or "")[:40], "  [ADMIN]" if admin else ""))

    # APIs fired by this route
    route_apis = []
    for r in recs:
        network_log.append({"route": cur, **r})
        if r.get("type") not in ("XHR", "Fetch"):
            continue
        k = api_key(r.get("method", "GET"), r.get("url", ""))
        is_file = any(h in r.get("url", "").lower() for h in FILE_HINTS)
        slot = apis.setdefault(k, {"methods": set(), "statuses": set(), "types": set(),
                                   "routes": set(), "full_url": r.get("url", ""), "is_file": False,
                                   "sources": set()})
        slot.setdefault("sources", set()).add("runtime")
        if not slot.get("full_url"):
            slot["full_url"] = r.get("url", "")
        slot["methods"].add((r.get("method") or "").upper())
        if r.get("status") is not None:
            slot["statuses"].add(r.get("status"))
        slot["types"].add(r.get("type"))
        slot["routes"].add(cur)
        slot["is_file"] = slot["is_file"] or is_file
        route_apis.append(k)
        # permission signal from API status
        if r.get("status") in (401, 403):
            perm_signals.append({"route": cur, "kind": "denied-api",
                                 "detail": "%s -> %s" % (k, r.get("status"))})

    features = [b["text"] for b in data.get("buttons", []) if not b["disabled"]]
    disabled = [b["text"] for b in data.get("buttons", []) if b["disabled"]]
    for d in disabled:
        perm_signals.append({"route": cur, "kind": "disabled-control", "detail": d})
    bt = (data.get("bodyText") or "").lower()
    for w in PERM_WORDS:
        if w in bt:
            perm_signals.append({"route": cur, "kind": "page-message", "detail": w}); break

    # file controls
    for fi in data.get("fileInputs", []):
        file_ctrls.append({"route": cur, "kind": "file-upload-input", "label": fi.get("name") or "(unnamed)"})
    for dl in data.get("downloads", []):
        file_ctrls.append({"route": cur, "kind": "download-link", "label": dl.get("text") or dl.get("href")})
    for b in data.get("buttons", []):
        if any(h in b["text"].lower() for h in FILE_HINTS):
            file_ctrls.append({"route": cur, "kind": "file-button", "label": b["text"]})

    # next routes
    next_routes = []
    for l in (data.get("nav", []) + data.get("links", [])):
        h = norm(l.get("href"))
        if h and same_origin(h):
            next_routes.append(h)
            if h not in seen and h not in queue:
                queue.append(h)
    next_routes = sorted(set(next_routes))

    route = {"url": cur, "title": title, "headings": headings, "admin": admin,
             "features": sorted(set(features))[:40], "apis": sorted(set(route_apis)),
             "links": next_routes[:40],
             "files": [f["label"] for f in file_ctrls if f["route"] == cur]}
    routes.append(route)
    if admin:
        admin_routes.append(route)

# ---- write graphify-ready markdown (explicit relationship sentences) ----
def w(name, text):
    with open(os.path.join(RAW, name), "w", encoding="utf-8") as f:
        f.write(text)

# 0. overview / god node
ov = ["# System: %s\n" % SYSTEM,
      "Start URL: %s\n" % START,
      "This document maps the architecture of the **%s** web system." % SYSTEM,
      "Crawled %d routes, %d distinct API endpoints, %d admin routes, %d file controls, %d permission signals.\n" %
      (len(routes), len(apis), len(admin_routes), len(file_ctrls), len(perm_signals)),
      "The %s system contains the following maps: Route Map, API Map, Feature Map, Permission Map, Admin Map, File-Handling Map.\n" % SYSTEM]
w("00_overview.md", "\n".join(ov))

# 1. routes
rt = ["# Route Map of %s\n" % SYSTEM]
for r in routes:
    rt.append("## Route %s" % (urlparse(r["url"]).path or "/"))
    rt.append("- Full URL: %s" % r["url"])
    rt.append("- Belongs to system: %s" % SYSTEM)
    if r["title"]:
        rt.append("- Page title: %s" % r["title"])
    if r["headings"]:
        rt.append("- Sections: %s" % ", ".join(r["headings"]))
    rt.append("- Access level: %s" % ("admin-only" if r["admin"] else "authenticated user"))
    if r["features"]:
        rt.append("- Route %s provides features: %s" % (urlparse(r["url"]).path or "/", "; ".join(r["features"])))
    for k in r["apis"]:
        rt.append("- Route %s calls API %s" % (urlparse(r["url"]).path or "/", k))
    for l in r["links"]:
        rt.append("- Route %s links to route %s" % (urlparse(r["url"]).path or "/", urlparse(l).path or "/"))
    rt.append("")
w("01_routes.md", "\n".join(rt))

# 2. apis
ap = ["# API Map of %s\n" % SYSTEM]
for k, v in sorted(apis.items()):
    ap.append("## API %s" % k)
    ap.append("- Full URL: %s" % v["full_url"])
    ap.append("- Methods: %s" % (", ".join(sorted(m for m in v["methods"] if m)) or "(unknown)"))
    ap.append("- Discovered via: %s" % ", ".join(sorted(v.get("sources") or {"runtime"})))
    obs = ", ".join(str(s) for s in sorted(v["statuses"]))
    ap.append("- Status codes observed: %s" % (obs or "not yet called at runtime (static only)"))
    ap.append("- Request type: %s" % (", ".join(sorted(t for t in v["types"] if t)) or "n/a"))
    ap.append("- API %s handles files: %s" % (k, "yes" if v["is_file"] else "no"))
    for rt_ in sorted(v["routes"]):
        ap.append("- API %s is called by route %s" % (k, urlparse(rt_).path or "/"))
    ap.append("")
w("02_apis.md", "\n".join(ap))

# 3. features
ft = ["# Feature Map of %s\n" % SYSTEM]
for r in routes:
    if not r["features"]:
        continue
    p = urlparse(r["url"]).path or "/"
    ft.append("## Features on route %s" % p)
    for feat in r["features"]:
        ft.append("- Feature \"%s\" is available on route %s of system %s" % (feat, p, SYSTEM))
    ft.append("")
w("03_features.md", "\n".join(ft))

# 4. permissions
pm = ["# Permission Map of %s\n" % SYSTEM,
      "Permission signals observed for the current logged-in role.\n"]
if not perm_signals:
    pm.append("- No explicit permission restrictions were observed for the current role.\n")
for s in perm_signals:
    p = urlparse(s["route"]).path or "/"
    if s["kind"] == "denied-api":
        pm.append("- Route %s was denied access to API %s (permission restriction)" % (p, s["detail"]))
    elif s["kind"] == "disabled-control":
        pm.append("- Feature \"%s\" on route %s is disabled for the current role (permission-gated)" % (s["detail"], p))
    elif s["kind"] == "page-message":
        pm.append("- Route %s shows a permission message: %s" % (p, s["detail"]))
w("04_permissions.md", "\n".join(pm))

# 5. admin
am = ["# Admin / Management Map of %s\n" % SYSTEM]
if not admin_routes:
    am.append("- No admin/management routes were reachable by the current role.\n")
for r in admin_routes:
    p = urlparse(r["url"]).path or "/"
    am.append("## Admin route %s" % p)
    am.append("- Admin route %s belongs to the management area of system %s" % (p, SYSTEM))
    if r["title"]:
        am.append("- Title: %s" % r["title"])
    for feat in r["features"]:
        am.append("- Admin feature \"%s\" is available on admin route %s" % (feat, p))
    for k in r["apis"]:
        am.append("- Admin route %s calls API %s" % (p, k))
    am.append("")
w("05_admin.md", "\n".join(am))

# 6. files
fm = ["# File-Handling Map of %s\n" % SYSTEM]
if not file_ctrls:
    fm.append("- No file upload/download/import/export controls were observed.\n")
for f in file_ctrls:
    p = urlparse(f["route"]).path or "/"
    fm.append("- %s \"%s\" on route %s handles files in system %s" % (f["kind"], f["label"], p, SYSTEM))
fm.append("")
for k, v in sorted(apis.items()):
    if v["is_file"]:
        fm.append("- API %s is a file-handling endpoint" % k)
w("06_files.md", "\n".join(fm))

# ---- deterministic knowledge graph (no LLM) -----------------------------
# The six maps above are already structured, so we build graph.json directly
# instead of asking an LLM to re-extract it (which is lossy on long entity
# lists). graphify cluster-only then adds communities + report + HTML. This
# makes the local graph 100% faithful to the recon, independent of model.
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_") or "x"

def _node(nid, label, source_file, ntype, **extra):
    n = {"label": label, "file_type": "concept", "source_file": source_file,
         "source_location": None, "source_url": ORIGIN, "captured_at": None,
         "author": None, "contributor": None, "type": ntype,
         "norm_label": (label or "").lower(), "id": nid}
    n.update(extra)
    return n

def _edge(s, t, rel, source_file):
    return {"relation": rel, "confidence": "EXTRACTED", "confidence_score": 1.0,
            "source_file": source_file, "source_location": None, "weight": 1.0,
            "source": s, "target": t}

gnodes, gedges = {}, []
def _addn(n):
    gnodes.setdefault(n["id"], n)

sys_id = "sys_" + _slug(SYSTEM)
_addn(_node(sys_id, "System: %s" % SYSTEM, "00_overview.md", "system"))

route_id = {}
for r in routes:
    p = urlparse(r["url"]).path or "/"
    rid = "route_" + _slug(p)
    route_id[norm(r["url"])] = rid
    _addn(_node(rid, "Route %s" % p, "01_routes.md",
                "admin-route" if r["admin"] else "route"))
    gedges.append(_edge(sys_id, rid, "contains", "00_overview.md"))

api_id = {}
for k, v in apis.items():
    aid = "api_" + _slug(k)
    api_id[k] = aid
    _addn(_node(aid, "API %s" % k, "02_apis.md",
                "file-api" if v["is_file"] else "api",
                methods=sorted(m for m in v["methods"] if m),
                status_codes=sorted(v["statuses"]),
                discovered_via=sorted(v.get("sources") or [])))
    gedges.append(_edge(sys_id, aid, "contains", "00_overview.md"))

for r in routes:
    rid = route_id[norm(r["url"])]
    for k in r["apis"]:
        if k in api_id:
            gedges.append(_edge(rid, api_id[k], "calls", "01_routes.md"))
    for l in r["links"]:
        tgt = route_id.get(norm(l))
        if tgt and tgt != rid:
            gedges.append(_edge(rid, tgt, "links_to", "01_routes.md"))

feat_seen = set()
for r in routes:
    p = urlparse(r["url"]).path or "/"
    rid = route_id[norm(r["url"])]
    for feat in r["features"]:
        fid = "feat_" + _slug(p + "_" + feat)
        if fid not in feat_seen:
            feat_seen.add(fid)
            _addn(_node(fid, "Feature \"%s\"" % feat, "03_features.md", "feature"))
        gedges.append(_edge(rid, fid, "provides", "03_features.md"))

file_seen = set()
for f in file_ctrls:
    p = urlparse(f["route"]).path or "/"
    fid = "file_" + _slug(p + "_" + f["kind"] + "_" + f["label"])
    if fid in file_seen:
        continue
    file_seen.add(fid)
    _addn(_node(fid, "%s \"%s\"" % (f["kind"], f["label"]), "06_files.md", "file-control"))
    rid = route_id.get(norm(f["route"]))
    if rid:
        gedges.append(_edge(rid, fid, "handles_files_via", "06_files.md"))

for i, s in enumerate(perm_signals):
    p = urlparse(s["route"]).path or "/"
    rid = route_id.get(norm(s["route"]))
    pid = "perm_" + _slug(p + "_" + s["kind"] + "_" + str(i))
    _addn(_node(pid, "Permission: %s on %s" % (s["detail"], p), "04_permissions.md", "permission"))
    if rid:
        gedges.append(_edge(pid, rid, "restricts", "04_permissions.md"))
    if s["kind"] == "denied-api":
        key = s["detail"].split(" -> ")[0].strip()
        if key in api_id:
            gedges.append(_edge(pid, api_id[key], "denies_access_to", "04_permissions.md"))

gpath = os.path.join(RAW, "graphify-out")
os.makedirs(gpath, exist_ok=True)
graph = {"directed": False, "multigraph": False, "graph": {},
         "nodes": list(gnodes.values()), "links": gedges, "hyperedges": []}
with open(os.path.join(gpath, "graph.json"), "w", encoding="utf-8") as f:
    json.dump(graph, f, ensure_ascii=False, indent=1)
print("sysmap: wrote deterministic graph.json: %d nodes, %d edges" % (len(gnodes), len(gedges)))

# raw network log (reference, not for the graph)
with open(os.path.join(OUT, "network.jsonl"), "w", encoding="utf-8") as f:
    for rec in network_log:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print("\nsysmap done. wrote %d markdown maps to %s" % (7, RAW))
print("  routes=%d apis=%d admin=%d files=%d perm-signals=%d network-records=%d" %
      (len(routes), len(apis), len(admin_routes), len(file_ctrls), len(perm_signals), len(network_log)))
print("next: run graphify on %s" % RAW)
