# ==============================================================================
# تقرير زيارات الفروع (التسويق والتشغيل) — Template 1786228
# GitHub Actions script — yesterday's visits -> PDF (with photos) -> email
# ==============================================================================

import os
import re
import io
import ast
import json
import html
import base64
import asyncio
import smtplib
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from PIL import Image, ImageOps
from playwright.async_api import async_playwright

Image.MAX_IMAGE_PIXELS = None

# ==============================================================================
# CONFIG  (secrets injected via GitHub Actions env)
# ==============================================================================
ZENPUT_API_KEY = os.environ["ZENPUT_API_KEY"]
GMAIL_PASS     = os.environ.get("GMAIL_PASS", "")
SEND_EMAIL     = os.environ.get("SEND_EMAIL", "true").strip().lower() != "false"

GMAIL_USER = "aof.group.auto@gmail.com"
TO_EMAIL   = "s.alharbi@aofgroup.com"
CC_EMAIL   = ["a.alsalem@aofgroup.com", "o.salahaddin@aofgroup.com"]

TEMPLATE_ID   = 1786228
EXPECTED_LEN  = 107
KSA           = ZoneInfo("Asia/Riyadh")
HEADERS       = {"X-API-TOKEN": ZENPUT_API_KEY}

PHOTO_MAX_PX  = 420     # longest side of embedded thumbnails
PHOTO_QUALITY = 68
PHOTO_WORKERS = 8

# Optional override: REPORT_DATE=YYYY-MM-DD (workflow_dispatch input)
_override   = os.environ.get("REPORT_DATE", "").strip()
REPORT_DATE = (datetime.strptime(_override, "%Y-%m-%d").date() if _override
               else datetime.now(KSA).date() - timedelta(days=1))
print(f"Report date: {REPORT_DATE}")

# ==============================================================================
# FORM LAYOUT (answer position, 1-based -> expected title)
# Generic titles ("Photo", "Text", "صورة الطلب", "ان وجد") repeat, so fields are
# read by position and every position is checked against its expected title.
# ==============================================================================
EXPECTED_TITLES = {
    1: 'Location',
    4: 'هل جميع العروض المتاحة في الوقت الحالي متاحة بالفرع؟',
    5: 'Photo', 6: 'Text', 7: 'Photo', 8: 'Text',
    9: 'هل المظهر العام الداخلي للفرع جيد حسب المعتمد من التسويق؟',
    10: 'Photo', 11: 'Text',
    12: 'هل تجربة المحلي جيدة ولا عليها اي ملاحظات؟',
    13: 'Photo', 14: 'Text',
    15: 'تقييم اثر الحملات والعروض على الفرع', 16: 'Text',
    17: 'هل يوجد اي توصيات تخص الفروع بالاجمال او الفرع بشكل خاص؟', 18: 'Text',
    19: 'هل المظهر العام الخارجي للفرع جيد حسب المعتمد من التسويق؟',
    20: 'هل يوجد احد نقاط الطلب الذاتيه؟ (كاشير ذاتي او فلاي ثرو)',
    21: 'صورة نقطة البيع', 22: 'اكتب نقطة البيع',
    23: 'هل الفرع متبع للاجراءات القياسية الخاصة بالطلب الذاتي؟',
    24: 'Photo', 25: 'Text',
    26: 'يوجد اي فرصه لاضافة احد نقاط الطلب الذاتية؟',
    27: 'Photo', 28: 'Text',
    29: 'هل الفرع درايف ثرو؟',
    30: 'صورة لشاشة قياس وقت الخدمة',
    31: 'وقت الخدمة للدرايف ثرو',
    32: 'هل نظام الدرايف ثرو يعمل بشكل جيد؟',
    33: 'صورة لنظام الدرايف ثرو (سماعات - مايك - سبيكر)',
    34: 'صورة لشاشة الدرايف ثرو',
    35: 'صورة للوحات الارشادية الخاصة بالدرايف ثرو',
    36: 'هل تتم خدمة عميل الدرايف ثرو بشكل جيد؟',
    37: 'كتابة الملاحظات',
    38: 'كتابة اي ملاحظات تشغيلية او تقنية',
    39: 'وقت الخدمة للاقريقيتور', 40: 'صورة الطلب',
    41: 'وقت الخدمة للعميل المباشر', 42: 'صورة الطلب',
    43: 'هل شبكات مدى مرتبطه بالكاشير؟', 44: 'Photo', 45: 'Text',
    47: '%المنتج النهائي',
    49: 'اسم المنتج', 50: 'صور المنتج كاملة',
    51: 'تغليف المنتج صحيح؟', 52: 'Photo',
    53: 'تقميرالمنتج صحيح؟', 54: 'Photo',
    55: 'مكونات المنتج صحيحة؟', 56: 'Photo',
    57: 'كميات المنتج صحيحة؟', 58: 'Photo',
    59: 'طعم المنتج سليم؟', 60: 'Photo',
    61: 'رائحة المنتج سليمة؟', 62: 'Photo',
    63: 'شكل المنتج النهائي مطابق للمواصفات؟', 64: 'Photo',
    65: 'هل يتم اتباع اجراءات التحضير للمنتجات بالفرع؟', 66: 'Photo',
    68: 'هل يوجد بالفرع اي خلل تشغيلي قد يؤثر على مبيعات الفرع بشكل مباشر؟',
    69: 'Photo', 70: 'Text',
    71: 'هل يوجد اي اجراءات مطلوبه من التسويق يجب العمل عليها فوراً؟',
    72: 'Text', 73: 'ان وجد',
    74: 'هل يوجد اي اجراءات مطلوبه من التشغيل يجب العمل عليها فوراً؟',
    75: 'Text', 76: 'ان وجد',
    77: 'هل جميع الاسعار مطابقة وصحيحة؟', 78: 'Photo', 79: 'Text', 80: 'ان وجد',
    82: 'قيم تجربة عميل فعلي متواجد بالفرع',
    83: 'هل تم توجيه العميل لاحد نقاط الطلب الذاتي؟',
    84: '%تجربة العميل',
    85: 'هل تم استقبال العميل بشكل صحيح؟', 86: 'Text',
    87: 'هل تم اخذ طلب العميل بشكل صحيح؟', 88: 'Text',
    89: 'هل تم اقتراح اصناف جانبية للعميل؟', 90: 'Text',
    91: 'هل تم تسليم الفاتورة للعميل؟', 92: 'Text',
    93: 'هل تم شكر العميل؟', 94: 'Text',
    95: 'هل تم ابلاغ العميل بوقت الخدمة المتوقع لتحضير طلبه؟', 96: 'Text',
    97: 'هل تم تحضير الطلب للعميل بشكل صحيح وحسب الطلب؟', 98: 'Text',
    99: 'هل تم تسليم الطلب للعميل بالشكل الصحيح؟', 100: 'Text',
    102: 'هل الفرع ملتزم بتصوير طلبات الاقريقيتور على بلورة؟',
    103: 'Photo', 104: 'Text',
    105: 'هل تم تحديد منطقة محددة لتجميع الطلبات؟',
    106: 'في حال نعم صور المنطقة / في حال لا صور المنطقة المقترحة',
    107: 'Text',
}

# pol: good   -> "Yes" is compliant
#      bad    -> "Yes" is a problem
#      action -> "Yes" means an action is required (counted as action item)
#      info   -> informational only (not scored)
# dep: position of a yes/no that must be "Yes" for this check to apply
GROUPS = [
    ("العروض والمظهر العام", [
        dict(q=4,  photos=[5],  note=6,  pol="good", label="جميع العروض الحالية متاحة بالفرع"),
        dict(q=19, photos=[7],  note=8,  pol="good", label="المظهر الخارجي حسب معتمد التسويق"),
        dict(q=9,  photos=[10], note=11, pol="good", label="المظهر الداخلي حسب معتمد التسويق"),
        dict(q=12, photos=[13], note=14, pol="good", label="تجربة المحلي جيدة بدون ملاحظات"),
        dict(q=15, photos=[],   note=16, pol="info", label="أثر الحملات والعروض على الفرع"),
        dict(q=17, photos=[],   note=18, pol="info", label="توصيات تخص الفرع"),
    ]),
    ("نقاط الطلب الذاتي", [
        dict(q=20, photos=[21], note=22, pol="info", label="يوجد نقطة طلب ذاتي (كاشير ذاتي / فلاي ثرو)"),
        dict(q=23, photos=[24], note=25, pol="good", label="الالتزام بالإجراءات القياسية للطلب الذاتي", dep=20),
        dict(q=26, photos=[27], note=28, pol="info", label="فرصة لإضافة نقطة طلب ذاتي"),
    ]),
    ("الدرايف ثرو", [
        dict(q=29, photos=[],   note=None, pol="info", label="الفرع درايف ثرو"),
        dict(q=32, photos=[33, 34, 35], note=38, pol="good", label="نظام الدرايف ثرو يعمل بشكل جيد", dep=29),
        dict(q=36, photos=[],   note=37, pol="good", label="خدمة عميل الدرايف ثرو جيدة", dep=29),
    ]),
    ("الدفع", [
        dict(q=43, photos=[44], note=45, pol="good", label="شبكات مدى مرتبطة بالكاشير"),
    ]),
    ("التوثيق لإدارة التسويق والتشغيل", [
        dict(q=68, photos=[69], note=70, pol="bad",    label="خلل تشغيلي يؤثر على مبيعات الفرع"),
        dict(q=71, photos=[73], note=72, pol="action", label="إجراءات مطلوبة من التسويق فوراً"),
        dict(q=74, photos=[76], note=75, pol="action", label="إجراءات مطلوبة من التشغيل فوراً"),
        dict(q=77, photos=[78, 80], note=79, pol="good", label="جميع الأسعار مطابقة وصحيحة"),
    ]),
    ("طلبات الأقريقيتور ومنطقة التجميع", [
        dict(q=102, photos=[103], note=104, pol="good", label="الالتزام بتصوير طلبات الأقريقيتور على البلورة"),
        dict(q=105, photos=[106], note=107, pol="good", label="تحديد منطقة لتجميع الطلبات"),
    ]),
]

PRODUCT_CHECKS = [
    (51, 52, "التغليف"), (53, 54, "التقمير"), (55, 56, "المكونات"),
    (57, 58, "الكميات"), (59, 60, "الطعم"),   (61, 62, "الرائحة"),
    (63, 64, "الشكل النهائي مطابق للمواصفات"), (65, 66, "اتباع إجراءات التحضير"),
]

CX_CHECKS = [
    (83, None, "توجيه العميل لنقاط الطلب الذاتي"),
    (85, 86, "استقبال العميل"), (87, 88, "أخذ الطلب"),
    (89, 90, "اقتراح أصناف جانبية"), (91, 92, "تسليم الفاتورة"),
    (93, 94, "شكر العميل"), (95, 96, "إبلاغ العميل بوقت الخدمة"),
    (97, 98, "تحضير الطلب حسب الطلب"), (99, 100, "تسليم الطلب بالشكل الصحيح"),
]

SERVICE_TIMES = [   # (value pos, photo positions, label, depends-on)
    (31, [30], "الدرايف ثرو", 29),
    (39, [40], "الأقريقيتور", None),
    (41, [42], "العميل المباشر", None),
]

# ==============================================================================
# 1. FETCH  (API returns newest first; all date filtering is client-side)
# ==============================================================================
def visit_date(s):
    """Visit date = when the visit was started (date_created_local), so visits
    that run past midnight stay on the day they happened. Falls back to submit."""
    meta = s.get("smetadata") or {}
    return (meta.get("date_created_local") or meta.get("date_submitted_local") or "")[:10]

def fetch_submissions(template_id, day):
    url, records, offset = "https://www.zenput.com/api/v3/submissions/", [], 0
    day_s = str(day)
    while True:
        r = requests.get(url, headers=HEADERS, timeout=60,
                         params={"form_template_id": template_id, "limit": 100, "start": offset})
        r.raise_for_status()
        batch = r.json().get("data", [])
        if not batch:
            break
        stop = False
        for s in batch:
            sub_day = ((s.get("smetadata") or {}).get("date_submitted_local") or "")[:10]
            if sub_day and sub_day < day_s:      # submitted before the day -> started before too
                stop = True
                break
            if visit_date(s) == day_s:
                records.append(s)
        if stop or len(batch) < 100:
            break
        offset += 100
    print(f"  Fetched {len(records)} visits for {day_s}")
    return records

# ==============================================================================
# 2. PARSE
# ==============================================================================
def norm_title(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()

def yn(a):
    v = a.get("value")
    if v is None:
        v = a.get("display_value")
    s = str(v).strip().lower() if v is not None else ""
    if s in ("true", "yes", "1", "نعم"):  return True
    if s in ("false", "no", "0", "لا"):   return False
    return None

def txt(a):
    v = a.get("display_value")
    if v in (None, "", []):
        v = a.get("value")
    if v is None:
        return ""
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    s = str(v).strip()
    return "" if s.lower() == "none" else s

def num(a):
    try:
        v = a.get("value")
        return float(v) if v not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None

def photo_keys(a):
    v = a.get("value")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            try:
                v = ast.literal_eval(v)
            except Exception:
                v = []
    if isinstance(v, dict):
        v = [v]
    keys = []
    for it in (v or []):
        if isinstance(it, dict) and it.get("s3_key"):
            keys.append(it["s3_key"])
    return keys

def clean_branch(name):
    return re.sub(r"\s+", " ", str(name or "").replace("\t", " ")).strip()

def parse_submission(s):
    meta = s.get("smetadata") or {}
    ans  = s.get("answers") or []

    def A(pos):
        return ans[pos - 1] if 0 < pos <= len(ans) else {}

    # layout check
    issues = []
    if len(ans) != EXPECTED_LEN:
        issues.append(f"answers={len(ans)} (expected {EXPECTED_LEN})")
    for pos, exp in EXPECTED_TITLES.items():
        got = norm_title(A(pos).get("title"))
        if got != norm_title(exp):
            issues.append(f"#{pos}: '{got}' != '{exp}'")

    loc  = meta.get("location") or {}
    cb   = meta.get("created_by") or {}
    branch = clean_branch(loc.get("name") if isinstance(loc, dict) else loc) or clean_branch(txt(A(1)))

    def check(c):
        dep_ok = True
        if c.get("dep"):
            dep_ok = yn(A(c["dep"])) is True
        val = yn(A(c["q"])) if dep_ok else None
        photos = [k for p in c.get("photos", []) for k in photo_keys(A(p))] if dep_ok else []
        note = txt(A(c["note"])) if (c.get("note") and dep_ok) else ""
        return {"label": c["label"], "pol": c["pol"], "val": val,
                "applicable": dep_ok, "photos": photos, "note": note}

    groups = [(g, [check(c) for c in checks]) for g, checks in GROUPS]

    product = {
        "pct": num(A(47)),
        "name": txt(A(49)),
        "photos": photo_keys(A(50)),
        "checks": [{"label": lbl, "val": yn(A(q)), "photos": photo_keys(A(p))}
                   for q, p, lbl in PRODUCT_CHECKS],
    }

    cx_rows = [{"label": lbl, "val": yn(A(q)), "note": txt(A(n)) if n else ""}
               for q, n, lbl in CX_CHECKS]
    cx = {"pct": num(A(84)), "rows": cx_rows,
          "evaluated": any(r["val"] is not None for r in cx_rows[1:])}

    times = []
    for pos, photos, lbl, dep in SERVICE_TIMES:
        applicable = (yn(A(dep)) is True) if dep else True
        times.append({"label": lbl, "applicable": applicable,
                      "value": num(A(pos)) if applicable else None,
                      "photos": [k for p in photos for k in photo_keys(A(p))] if applicable else []})

    sub = {
        "id": s.get("id"),
        "branch": branch,
        "visitor": (cb.get("display_name") if isinstance(cb, dict) else "") or "",
        "started": (meta.get("date_created_local") or "")[:16].replace("T", " "),
        "submitted": (meta.get("date_submitted_local") or "")[:16].replace("T", " "),
        "groups": groups, "product": product, "cx": cx, "times": times,
        "layout_issues": issues,
    }

    # scoring
    scored = [c for _, cs in groups for c in cs if c["pol"] in ("good", "bad") and c["val"] is not None]
    passed = sum(1 for c in scored if (c["val"] if c["pol"] == "good" else not c["val"]))
    sub["n_scored"] = len(scored)
    sub["n_passed"] = passed
    sub["compliance"] = round(passed / len(scored) * 100, 1) if scored else None
    sub["fails"] = [c for c in scored if (c["val"] is False if c["pol"] == "good" else c["val"] is True)]
    sub["actions"] = [c for _, cs in groups for c in cs if c["pol"] == "action" and c["val"] is True]
    sub["product_fails"] = [p["label"] for p in product["checks"] if p["val"] is False]
    return sub

print("Fetching data...")
raw_subs = fetch_submissions(TEMPLATE_ID, REPORT_DATE)
visits   = [parse_submission(s) for s in raw_subs]
visits.sort(key=lambda v: v["started"] or v["submitted"])
for v in visits:
    print(f"  {v['branch']:<45} started {v['started']}  submitted {v['submitted']}  "
          f"compliance={v['compliance']}  product={v['product']['pct']}")
    if v["layout_issues"]:
        print(f"    !! LAYOUT MISMATCH ({len(v['layout_issues'])}): {v['layout_issues'][:5]}")

# ==============================================================================
# 3. PHOTOS  (s3_key -> signed URL -> thumbnail, all in this run)
# ==============================================================================
def fetch_thumb(s3_key):
    try:
        r = requests.get("https://www.zenput.com/api/v2/users/current/storage/",
                         headers=HEADERS, params={"path": s3_key}, timeout=30)
        r.raise_for_status()
        url = (r.json().get("data") or {}).get("location")
        if not url:
            return s3_key, None
        img_r = requests.get(url, timeout=60)
        img_r.raise_for_status()
        img = Image.open(io.BytesIO(img_r.content))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=PHOTO_QUALITY, optimize=True)
        return s3_key, "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"    photo failed: {s3_key[-40:]} -> {e}")
        return s3_key, None

def all_keys(v):
    keys = []
    for _, cs in v["groups"]:
        for c in cs: keys += c["photos"]
    keys += v["product"]["photos"]
    for p in v["product"]["checks"]: keys += p["photos"]
    for t in v["times"]: keys += t["photos"]
    return keys

unique_keys = list(dict.fromkeys(k for v in visits for k in all_keys(v)))
print(f"Downloading {len(unique_keys)} photos...")
with ThreadPoolExecutor(max_workers=PHOTO_WORKERS) as ex:
    THUMBS = dict(ex.map(fetch_thumb, unique_keys))
print(f"  OK: {sum(1 for x in THUMBS.values() if x)} / {len(unique_keys)}")

# ==============================================================================
# 4. HTML
# ==============================================================================
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Cairo', sans-serif; direction: rtl; text-align: right; background: #f0f2f5; color: #2d3436; padding: 20px; }
.container { width: 1300px; margin: 0 auto; }
.header { background: linear-gradient(135deg, #6f42c1 0%, #4a1a8d 100%); color: white; border-radius: 12px; padding: 28px 40px; margin-bottom: 22px; text-align: center; }
.header h1 { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
.header .subtitle { font-size: 15px; opacity: 0.88; }
.section-title { font-size: 19px; font-weight: 700; color: #6f42c1; border-right: 5px solid #6f42c1; padding-right: 12px; margin: 26px 0 14px; break-after: avoid; }
.kpi-grid { display: grid; grid-template-columns: repeat(6,1fr); gap: 12px; margin-bottom: 20px; }
.kpi-card { background: white; border-radius: 10px; padding: 16px 10px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08); border-top: 4px solid #6f42c1; break-inside: avoid; }
.kpi-label { font-size: 13px; color: #636e72; margin-bottom: 6px; }
.kpi-value { font-size: 30px; font-weight: 700; }
.kpi-sub   { font-size: 12px; color: #9aa3a8; margin-top: 3px; }
.table-wrap { background: white; border-radius: 10px; padding: 18px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead tr { background: #6f42c1; color: white; }
th { padding: 10px 8px; font-weight: 600; text-align: center; white-space: nowrap; }
td { padding: 9px 7px; border-bottom: 1px solid #f0f0f0; text-align: center; vertical-align: middle; }
tr { break-inside: avoid; }
.branch-name { text-align: right; font-weight: 600; }
.rank-badge { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; background: #e9ecef; font-weight: 700; font-size: 12px; color: #495057; }
.rank-badge.gold { background: #ffd700; color: #6d5700; } .rank-badge.silver { background: #c0c0c0; color: #4a4a4a; } .rank-badge.bronze { background: #cd7f32; color: white; }
.mini-bar  { height: 7px; background: #e9ecef; border-radius: 4px; overflow: hidden; margin-top: 3px; }
.mini-fill { height: 100%; border-radius: 4px; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; color: white; white-space: nowrap; }
.b-yes { background: #28a745; } .b-no { background: #dc3545; } .b-na { background: #b2bec3; color: #444; }
.b-info { background: #17a2b8; } .b-action { background: #fd7e14; } .b-none { background: #e9ecef; color: #555; }
.visit { background: white; border-radius: 10px; margin-bottom: 22px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; }
.visit-header { background: #6f42c1; color: white; padding: 14px 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; break-after: avoid; }
.visit-header h3 { font-size: 18px; font-weight: 700; }
.visit-header .meta { font-size: 13px; opacity: 0.9; }
.pill { background: rgba(255,255,255,0.2); border-radius: 8px; padding: 3px 10px; font-size: 12px; margin-left: 6px; }
.visit-body { padding: 16px 20px; }
.warn { background: #fff3cd; color: #856404; border: 1px solid #ffe08a; border-radius: 8px; padding: 8px 12px; font-size: 12px; margin-bottom: 12px; }
.group-title { font-size: 15px; font-weight: 700; color: #4a1a8d; background: #f3f0ff; border-radius: 6px; padding: 7px 12px; margin: 16px 0 8px; break-after: avoid; }
.check { display: grid; grid-template-columns: 300px 110px 1fr; gap: 12px; align-items: start; padding: 9px 4px; border-bottom: 1px solid #f2f2f2; break-inside: avoid; }
.check:last-child { border-bottom: none; }
.check .lbl { font-weight: 600; font-size: 13px; }
.check .note { font-size: 12.5px; color: #4a4a4a; line-height: 1.7; }
.check .note-empty { color: #b2bec3; font-size: 12px; }
.photos { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.photos img { height: 130px; width: auto; max-width: 200px; object-fit: cover; border-radius: 6px; border: 1px solid #e5e5e5; }
.photo-missing { height: 130px; width: 100px; border-radius: 6px; border: 1px dashed #ccc; color: #aaa; font-size: 11px; display: flex; align-items: center; justify-content: center; }
.stat-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 6px; }
.stat-box { border: 1px solid #eee; border-radius: 8px; padding: 10px 12px; break-inside: avoid; }
.stat-box .t { font-size: 12px; color: #636e72; }
.stat-box .v { font-size: 24px; font-weight: 700; }
.prod-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.prod-item { border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; break-inside: avoid; }
.prod-item .lbl { font-size: 12.5px; font-weight: 600; margin-bottom: 4px; }
.prod-item .photos img { height: 90px; max-width: 130px; }
.empty { color: #636e72; padding: 18px; }
"""

def pct_color(p):
    if p is None: return "#636e72"
    if p >= 85: return "#28a745"
    if p >= 70: return "#20c997"
    if p >= 60: return "#fd7e14"
    return "#dc3545"

def esc_multiline(s):
    return html.escape(s).replace("\n", "<br>")

def fmt_num(x):
    if x is None: return "—"
    return f"{x:.0f}" if float(x).is_integer() else f"{x:.1f}"

def badge(val, pol, applicable=True):
    if not applicable:
        return '<span class="badge b-na">لا ينطبق</span>'
    if val is None:
        return '<span class="badge b-na">—</span>'
    if pol == "good":
        return '<span class="badge b-yes">نعم</span>' if val else '<span class="badge b-no">لا</span>'
    if pol == "bad":
        return '<span class="badge b-no">نعم</span>' if val else '<span class="badge b-yes">لا</span>'
    if pol == "action":
        return '<span class="badge b-action">مطلوب</span>' if val else '<span class="badge b-none">لا يوجد</span>'
    return f'<span class="badge b-info">{"نعم" if val else "لا"}</span>'

def photos_html(keys):
    if not keys: return ""
    out = []
    for k in keys:
        src = THUMBS.get(k)
        out.append(f'<img src="{src}">' if src else '<div class="photo-missing">تعذر التحميل</div>')
    return f'<div class="photos">{"".join(out)}</div>'

def kpi(label, value, sub="", color="#2d3436", border="#6f42c1"):
    return (f'<div class="kpi-card" style="border-top-color:{border}">'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-value" style="color:{color}">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')

def avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def overall_kpis():
    comp  = avg([v["compliance"] for v in visits])
    prod  = avg([v["product"]["pct"] for v in visits])
    t = {lbl: avg([x["value"] for v in visits for x in v["times"] if x["label"] == lbl])
         for _, _, lbl, _ in SERVICE_TIMES}
    n_act = sum(len(v["actions"]) for v in visits)
    n_fail = sum(len(v["fails"]) for v in visits)
    return comp, prod, t, n_act, n_fail

def kpi_section():
    if not visits:
        return '<p class="empty">لا توجد زيارات مسجلة لهذا اليوم</p>'
    comp, prod, t, n_act, n_fail = overall_kpis()
    return f"""<div class="kpi-grid">
        {kpi("عدد الزيارات", len(visits), f"{len({v['branch'] for v in visits})} فرع")}
        {kpi("نسبة الالتزام", f"{fmt_num(comp)}%" if comp is not None else "—", f"{n_fail} ملاحظة", pct_color(comp), "#28a745")}
        {kpi("متوسط المنتج النهائي", f"{fmt_num(prod)}%" if prod is not None else "—", "اختبار المنتج", pct_color(prod), "#20c997")}
        {kpi("وقت الدرايف ثرو", fmt_num(t["الدرايف ثرو"]), "متوسط", border="#17a2b8")}
        {kpi("وقت الأقريقيتور / المباشر", f'{fmt_num(t["الأقريقيتور"])} / {fmt_num(t["العميل المباشر"])}', "متوسط", border="#17a2b8")}
        {kpi("إجراءات مطلوبة", n_act, "تسويق + تشغيل", "#fd7e14", "#fd7e14")}
    </div>"""

def rank_badge(i):
    cls = {0: "gold", 1: "silver", 2: "bronze"}.get(i, "")
    return f'<span class="rank-badge {cls}">{i+1}</span>'

def summary_table():
    if not visits:
        return ""
    ranked = sorted(visits, key=lambda v: (v["compliance"] is None, -(v["compliance"] or 0)))
    rows = ""
    for i, v in enumerate(ranked):
        c, p = v["compliance"], v["product"]["pct"]
        tm = {x["label"]: x for x in v["times"]}
        def tcell(lbl):
            x = tm[lbl]
            return "لا ينطبق" if not x["applicable"] else fmt_num(x["value"])
        rows += f"""<tr>
            <td>{rank_badge(i)}</td>
            <td class="branch-name">{html.escape(v['branch'])}</td>
            <td>{html.escape(v['visitor'])}</td>
            <td>{v['started'][11:] or '—'}</td>
            <td><span style="color:{pct_color(c)};font-weight:700">{fmt_num(c)}%</span>
                <div class="mini-bar"><div class="mini-fill" style="width:{c or 0}%;background:{pct_color(c)}"></div></div></td>
            <td><span style="color:{pct_color(p)};font-weight:700">{fmt_num(p)}%</span>
                <div class="mini-bar"><div class="mini-fill" style="width:{p or 0}%;background:{pct_color(p)}"></div></div></td>
            <td>{tcell('الدرايف ثرو')}</td><td>{tcell('الأقريقيتور')}</td><td>{tcell('العميل المباشر')}</td>
            <td style="color:#dc3545;font-weight:700">{len(v['fails'])}</td>
            <td style="color:#fd7e14;font-weight:700">{len(v['actions'])}</td>
        </tr>"""
    return f"""<div class="table-wrap"><table>
        <thead><tr><th>#</th><th>الفرع</th><th>الزائر</th><th>وقت البدء</th><th>نسبة الالتزام</th>
        <th>المنتج النهائي</th><th>وقت الدرايف ثرو</th><th>وقت الأقريقيتور</th><th>وقت المباشر</th>
        <th>ملاحظات</th><th>إجراءات مطلوبة</th></tr></thead>
        <tbody>{rows}</tbody></table></div>"""

def issues_table():
    rows = ""
    for v in visits:
        items = [(c["label"], c["note"], "ملاحظة") for c in v["fails"]] + \
                [(c["label"], c["note"], "إجراء") for c in v["actions"]]
        if v["product_fails"]:
            items.append(("اختبار المنتج: " + v["product"]["name"], "، ".join(v["product_fails"]), "منتج"))
        for lbl, note, kind in items:
            cls = {"ملاحظة": "b-no", "إجراء": "b-action", "منتج": "b-info"}[kind]
            rows += f"""<tr><td class="branch-name">{html.escape(v['branch'])}</td>
                <td><span class="badge {cls}">{kind}</span></td>
                <td style="text-align:right">{html.escape(lbl)}</td>
                <td style="text-align:right;font-size:12.5px">{esc_multiline(note) or '—'}</td></tr>"""
    if not rows:
        return ""
    return f"""<div class="section-title">ملخص الملاحظات والإجراءات المطلوبة</div>
        <div class="table-wrap"><table>
        <thead><tr><th>الفرع</th><th>النوع</th><th>البند</th><th>التفاصيل</th></tr></thead>
        <tbody>{rows}</tbody></table></div>"""

def visit_card(v):
    c, p = v["compliance"], v["product"]["pct"]
    warn = ""
    if v["layout_issues"]:
        warn = (f'<div class="warn">تنبيه: ترتيب أسئلة النموذج لا يطابق المتوقع '
                f'({len(v["layout_issues"])} اختلاف) — يرجى مراجعة البيانات.</div>')

    # service times
    tboxes = ""
    for x in v["times"]:
        val = "لا ينطبق" if not x["applicable"] else fmt_num(x["value"])
        tboxes += f"""<div class="stat-box"><div class="t">وقت الخدمة — {x['label']}</div>
            <div class="v">{val}</div>{photos_html(x['photos'])}</div>"""

    groups_html = ""
    for gname, checks in v["groups"]:
        rows = ""
        for ch in checks:
            note = (f'<div class="note">{esc_multiline(ch["note"])}</div>' if ch["note"]
                    else '<div class="note-empty">—</div>')
            rows += f"""<div class="check">
                <div class="lbl">{html.escape(ch['label'])}</div>
                <div>{badge(ch['val'], ch['pol'], ch['applicable'])}</div>
                <div>{note}{photos_html(ch['photos'])}</div></div>"""
        groups_html += f'<div class="group-title">{gname}</div>{rows}'

    # product test
    prod_items = ""
    for pc in v["product"]["checks"]:
        prod_items += f"""<div class="prod-item"><div class="lbl">{pc['label']}</div>
            {badge(pc['val'], 'good')}{photos_html(pc['photos'])}</div>"""
    product_html = f"""<div class="group-title">اختبار المنتج</div>
        <div class="check">
            <div class="lbl">المنتج: {html.escape(v['product']['name'] or '—')}</div>
            <div><span class="badge" style="background:{pct_color(p)}">{fmt_num(p)}%</span></div>
            <div>{photos_html(v['product']['photos'])}</div></div>
        <div class="prod-grid" style="margin-top:8px">{prod_items}</div>"""

    # customer experience
    cx = v["cx"]
    if cx["evaluated"]:
        cx_rows = ""
        for r in cx["rows"]:
            note = f'<div class="note">{esc_multiline(r["note"])}</div>' if r["note"] else '<div class="note-empty">—</div>'
            cx_rows += f"""<div class="check"><div class="lbl">{r['label']}</div>
                <div>{badge(r['val'], 'good')}</div><div>{note}</div></div>"""
        cx_html = (f'<div class="group-title">تقييم تجربة العميل — {fmt_num(cx["pct"])}%</div>{cx_rows}')
    else:
        first = cx["rows"][0]
        cx_html = (f'<div class="group-title">تقييم تجربة العميل</div>'
                   f'<div class="check"><div class="lbl">{first["label"]}</div>'
                   f'<div>{badge(first["val"], "good")}</div>'
                   f'<div class="note-empty">لم يتم تقييم باقي خطوات تجربة العميل</div></div>')

    return f"""<div class="visit">
        <div class="visit-header">
            <h3>{html.escape(v['branch'])}</h3>
            <div class="meta">
                <span class="pill">الزائر: {html.escape(v['visitor'])}</span>
                <span class="pill">البدء: {v['started']}</span>
                <span class="pill">الإرسال: {v['submitted']}</span>
                <span class="pill">الالتزام: {fmt_num(c)}% ({v['n_passed']}/{v['n_scored']})</span>
                <span class="pill">المنتج: {fmt_num(p)}%</span>
            </div>
        </div>
        <div class="visit-body">
            {warn}
            <div class="group-title">أوقات الخدمة</div>
            <div class="stat-row">{tboxes}</div>
            {groups_html}
            {product_html}
            {cx_html}
        </div>
    </div>"""

def build_html():
    n_br = len({v["branch"] for v in visits})
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl"><head><meta charset="UTF-8">
<title>تقرير زيارات الفروع — {REPORT_DATE}</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><div class="container">
    <div class="header">
        <h1>تقرير زيارات الفروع — التسويق والتشغيل</h1>
        <div class="subtitle">{REPORT_DATE} &nbsp;|&nbsp; {len(visits)} زيارة &nbsp;|&nbsp; {n_br} فرع</div>
    </div>
    <div class="section-title">مؤشرات الأداء العامة</div>
    {kpi_section()}
    {'<div class="section-title">ترتيب الفروع حسب نسبة الالتزام</div>' + summary_table() if visits else ''}
    {issues_table()}
    {'<div class="section-title">تفاصيل الزيارات</div>' if visits else ''}
    {''.join(visit_card(v) for v in visits)}
</div></body></html>"""

# ==============================================================================
# 5. PDF VIA PLAYWRIGHT (paginated; rows/photo blocks don't split across pages)
# ==============================================================================
async def build_pdf(html_content: str) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page(viewport={"width": 1380, "height": 1900})
        await page.set_content(html_content, wait_until="networkidle", timeout=120000)
        await page.wait_for_timeout(2000)
        pdf_bytes = await page.pdf(
            width="1380px", height="1950px", print_background=True,
            margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"},
        )
        await browser.close()
    return pdf_bytes

html_content = build_html()
with open(f"branch_visits_{REPORT_DATE}.html", "w", encoding="utf-8") as f:
    f.write(html_content)
print("Generating PDF...")
pdf_bytes = asyncio.run(build_pdf(html_content))
pdf_filename = f"branch_visits_report_{REPORT_DATE}.pdf"
with open(pdf_filename, "wb") as f:
    f.write(pdf_bytes)
print(f"  PDF size: {len(pdf_bytes):,} bytes")

# ==============================================================================
# 6. EMAIL  (no emoji)
# ==============================================================================
subject = f"تقرير زيارات الفروع (التسويق والتشغيل) — {REPORT_DATE}"

if visits:
    comp, prod, t, n_act, n_fail = overall_kpis()
    lines = [
        f"• عدد الزيارات: {len(visits)} زيارة في {len({v['branch'] for v in visits})} فرع",
        f"• نسبة الالتزام: {fmt_num(comp)}% ({n_fail} ملاحظة)",
        f"• متوسط المنتج النهائي: {fmt_num(prod)}%",
        f"• متوسط أوقات الخدمة — درايف ثرو: {fmt_num(t['الدرايف ثرو'])} | أقريقيتور: {fmt_num(t['الأقريقيتور'])} | مباشر: {fmt_num(t['العميل المباشر'])}",
        f"• إجراءات مطلوبة (تسويق + تشغيل): {n_act}",
    ]
    branch_lines = "<br>".join(
        f"- {html.escape(v['branch'])}: التزام {fmt_num(v['compliance'])}% | منتج {fmt_num(v['product']['pct'])}%"
        for v in sorted(visits, key=lambda v: -(v['compliance'] or 0)))
    summary_html = "<br>".join(lines) + "<br><br>" + branch_lines
else:
    summary_html = "لا توجد زيارات مسجلة لهذا اليوم."

body_html = f"""
<div dir="rtl" style="font-family:Cairo,Arial,sans-serif;font-size:14px;color:#2d3436;line-height:1.8">
  <p>السلام عليكم،</p>
  <p>مرفق تقرير زيارات الفروع (التسويق والتشغيل) ليوم <strong>{REPORT_DATE}</strong>.</p>
  <br>
  <p style="color:#6f42c1;font-weight:700">ملخص اليوم:</p>
  <p>{summary_html}</p>
  <br>
  <p style="color:#636e72;font-size:12px">التقرير التفصيلي مع الصور مرفق بصيغة PDF.</p>
  <br>
  <p>Business Intelligence<br>AOF Group</p>
</div>"""

if SEND_EMAIL:
    msg = MIMEMultipart("mixed")
    msg["From"]    = f"Business Intelligence <{GMAIL_USER}>"
    msg["To"]      = TO_EMAIL
    msg["Cc"]      = ", ".join(CC_EMAIL)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    part = MIMEApplication(pdf_bytes, _subtype="pdf")
    part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
    msg.attach(part)

    print("Sending email...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, [TO_EMAIL] + CC_EMAIL, msg.as_string())
    print(f"Email sent -> {TO_EMAIL}, CC: {CC_EMAIL}")
else:
    print("SEND_EMAIL=false -> email skipped")
