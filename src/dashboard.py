"""HTML 대시보드: 버전 변경 내역 · 자격 보유 인원 · 평가 결과를 한 화면에 (2단계 ②).

규약 (CLAUDE.md 5.5)
- 파이썬 기본 라이브러리(json, string.Template)만 쓴다. 외부 CSS·JS·CDN 없이 파일 하나로 인터넷 없이 열린다.
- LLM을 호출하지 않는다. 파싱·비교 결과, 자격 CSV 집계, 최신 라운드 평가 결과만 읽는다(같은 입력 → 같은 HTML).
- 사내 확인용이라 화면은 한국어, [내부 메모]도 보여 준다. 자격 현황은 숫자만 넣고 이름은 넣지 않는다.
- 버전 드롭다운은 HTML 안의 자바스크립트가 처리한다(버전별 데이터를 JSON으로 함께 넣는다).
- 입력 파일이 없는 칸은 "데이터 없음"/"미구현"으로 표시하고 멈추지 않는다.

실행: python -m src.dashboard  → reports/dashboard.html
"""
import json
import re
import sys
from collections import Counter
from string import Template

from src import config
from src.assessment import deliverables, diff, difficulty, parser
from src.assessment.readiness import LABEL_KO
from src.assessment.templates import embedded, load_templates, match

OUT_PATH = config.REPORTS_DIR / "dashboard.html"


# ── 데이터 모으기 ─────────────────────────────────────────────────────────

def version_data() -> dict:
    """버전별 요구사항 목록과 직전 버전 대비 변경 내역."""
    labels = parser.list_versions()
    versions = {}
    for i, label in enumerate(labels):
        data = parser.load(label)
        reqs = [{"id": r["id"], "title": r["title"], "sheet": r["sheet"], "area": r.get("area") or "",
                 "scope": "회사 차원" if r["scope"] == "company" else "고객 사례 4건",
                 "note": r.get("internal_note") or "", "text": r["text"]} for r in data["requirements"]]
        entry = {"label": label, "validity": data["version"]["validity_period"],
                 "total": len(reqs), "by_sheet": dict(Counter(r["sheet"] for r in reqs)),
                 "requirements": reqs, "diff": None}
        if i > 0:
            d = diff.compare(parser.load(labels[i - 1]), data)
            entry["diff"] = {
                "from": d["from_version"], "counts": d["counts"],
                "added": [{"id": a["id"], "title": a["title"], "note": a.get("internal_note") or ""} for a in d["added"]],
                "removed": [{"id": r["id"], "title": r["title"]} for r in d["removed"]],
                "changed": [{"id": c["id"], "title": c["title"], "type": c["change_type"],
                             "changes": c["changes"], "note": c.get("internal_note") or ""} for c in d["changed"]],
                "sheet_notes": [{"sheet": n["sheet"], "type": n["change_type"], "changes": n.get("changes", [])}
                                for n in d["sheet_notes_changed"]],
            }
        entry["difficulty"] = difficulty_data(label)
        entry["deliverables"] = deliverables_data(label)
        versions[label] = entry
    return {"labels": labels, "latest": labels[-1] if labels else None, "versions": versions}


def difficulty_data(label: str) -> dict:
    """버전의 난이도 분포와 항목별 점수 근거 (2단계 ③). 계산 오류가 나도 대시보드는 멈추지 않는다."""
    try:
        r = difficulty.assess(version=label)
    except Exception as e:  # noqa: BLE001 — 입력 파일 문제는 화면에 '데이터 없음'으로 보여 준다
        return {"error": f"{type(e).__name__}: {e}"}
    items = sorted(r["items"], key=lambda i: (-i["score"], i["id"]))
    return {"counts": r["counts"],
            "items": [{"id": i["id"], "title": i["title"], "level": i["level_ko"], "score": i["score"],
                       "readiness": LABEL_KO[i["readiness"]], "reasons": short_reasons(i)} for i in items]}


def short_reasons(item: dict) -> list[str]:
    """점수 근거를 화면용 짧은 한국어로 바꾼다(점수 규칙은 difficulty.py, 여기서는 표기만)."""
    out = [f"{LABEL_KO[item['readiness']]} +{difficulty.READINESS_POINTS.get(item['readiness'], 0)}"]
    for reason in item["reasons"][1:]:
        if "customer examples" in reason:
            out.append("고객 사례 4건 증빙 +1")
        elif "new in version" in reason:
            out.append("이번 버전 신규 +1")
        else:
            out.append(reason)
    return out


def deliverables_data(label: str) -> dict:
    """버전의 산출물 체크리스트 (2단계 ④). 미리 추출한 파일만 읽는다(LLM 호출 없음)."""
    try:
        r = deliverables.lookup(version=label)
    except Exception as e:  # noqa: BLE001 — 파일 문제는 화면에 '데이터 없음'으로 보여 준다
        return {"error": f"{type(e).__name__}: {e}"}
    if "error" in r:
        return {"error": r["error"]}

    def cases(n):
        if not n:
            return "회사 차원 (1회)"
        return "고객 사례 4건 모두" if n >= deliverables.CASES_TOTAL else f"고객 사례 4건 중 {n}건 이상"

    tpls = load_templates()  # 산출물 양식 연결(파이썬 규칙). 양식이 없으면 연결 없이 표시한다
    items = [{"id": i["id"], "title": i["title"], "cases": cases(i["customer_examples_required"]),
              "deliverables": [d["name"] for d in i["deliverables"]],
              "templates": [match(i["id"], d["name"], tpls) for d in i["deliverables"]]} for i in r["items"]]
    return {"total": sum(len(i["deliverables"]) for i in items),
            "linked": sum(1 for i in items for t in i["templates"] if t),
            "company": sum(1 for i in r["items"] if not i["customer_examples_required"]),
            "customer": sum(1 for i in r["items"] if i["customer_examples_required"]),
            "items": items}


def certification_data() -> dict | None:
    """자격 보유 숫자 집계(이름 없음). 가상 데이터가 없으면 None."""
    try:
        from src.workforce.certifications import load_certifications
        rows = load_certifications()
    except (FileNotFoundError, ImportError):
        return None
    divisions = sorted({r["division"] for r in rows})
    vendors = sorted({r["vendor"] for r in rows})
    by_div_vendor = Counter((r["division"], r["vendor"]) for r in rows)
    try:  # 대상 대비 실적(사내 취합 양식 구조). 대상 파일이 없으면 None
        from src.workforce.targets import load_targets, target_status
        targets = target_status() if load_targets() else None
    except Exception as e:  # noqa: BLE001 — 대상 데이터 문제로 대시보드가 멈추지 않게 한다
        targets = {"error": f"{type(e).__name__}: {e}"}
    return {
        "targets": targets,
        "total": len(rows),
        "employees": len({r["employee_id"] for r in rows}),
        "by_vendor": dict(sorted(Counter(r["vendor"] for r in rows).items())),
        "by_cert": sorted(([f"{r['vendor']} · {r['certification']}", n] for r, n in
                           Counter((r["vendor"], r["certification"]) for r in rows).items()
                           for r in [{"vendor": r[0], "certification": r[1]}]), key=lambda x: (-x[1], x[0])),
        "divisions": divisions, "vendors": vendors,
        "matrix": [[by_div_vendor.get((d, v), 0) for v in vendors] for d in divisions],
    }


def _round_no(path) -> int:
    return int(re.search(r"round(\d+)", path.name).group(1))


def evaluation_data() -> dict | None:
    """라운드별 추이와 최신 라운드 문항별 결과(답변 전문은 넣지 않는다)."""
    files = sorted(config.EVAL_DIR.glob("eval_result_round*.json"), key=_round_no)
    files = [f for f in files if _round_no(f) >= 1]  # 0은 시험 실행
    if not files:
        return None
    history = []
    for f in files:
        s = json.loads(f.read_text(encoding="utf-8"))["summary"]
        history.append({"round": _round_no(f), "passed": s["passed"], "total": s["total"],
                        "judge": s.get("judge_mean_score"),
                        "faithfulness": (s.get("ragas_mean") or {}).get("faithfulness")})
    latest = json.loads(files[-1].read_text(encoding="utf-8"))
    items = [{"id": r["id"], "type": r["type"], "question": r["question"], "user": r.get("user_id", "staff"),
              "passed": r["passed"], "detail": r["detail"], "judge": (r.get("judge") or {}).get("score"),
              "faith": (r.get("ragas") or {}).get("faithfulness")} for r in latest["results"]]
    return {"round": latest["round"], "run_at": latest.get("run_at"), "model": latest.get("model"),
            "summary": latest["summary"], "history": history, "items": items}


def benchmark_data() -> dict:
    """현주소 시트: 우리 회사 vs 익명 A사~E사(가상). 파일 문제로 대시보드가 멈추지 않게 오류는 칸에 표시한다."""
    try:
        from src.benchmark import status
        return status()
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def build_data() -> dict:
    return {"versions": version_data(), "certs": certification_data(), "eval": evaluation_data(),
            "templates": embedded(load_templates()), "benchmark": benchmark_data(), "not_implemented": []}


# ── HTML ──────────────────────────────────────────────────────────────────

PAGE = Template(r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CompassPilot 대시보드</title>
<style>
:root{color-scheme:light;--bg:#f6f7f9;--card:#fcfcfb;--fg:#0b0b0b;--fg2:#52514e;--muted:#6b6a65;--line:#e1e0d9;--accent:#2a78d6;--track:#cde2fb;--chip:#eef2fb;--other:#c3c2b7;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;--good-text:#006300;--bad-text:#b42318;--note:#8a5a00;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0d0d0d;--card:#1a1a19;--fg:#f0efec;--fg2:#c3c2b7;--muted:#a3a29b;--line:#2c2c2a;--accent:#3987e5;--track:#0d2a4d;--chip:#26304a;--other:#55544f;
--good-text:#0ca30c;--bad-text:#ff7b70;--note:#e0b050;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0d0d;--card:#1a1a19;--fg:#f0efec;--fg2:#c3c2b7;--muted:#a3a29b;--line:#2c2c2a;--accent:#3987e5;--track:#0d2a4d;--chip:#26304a;--other:#55544f;
--good-text:#0ca30c;--bad-text:#ff7b70;--note:#e0b050;--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif}
header{padding:20px 16px 8px;max-width:1200px;margin:auto}
.sheets{position:sticky;top:0;z-index:5;background:var(--bg);max-width:1200px;margin:auto;padding:8px 16px 0;display:flex;gap:4px;border-bottom:1px solid var(--line);overflow-x:auto}
.sheet-tab{font:inherit;font-weight:600;border:1px solid var(--line);border-bottom:0;border-radius:8px 8px 0 0;background:var(--chip);color:var(--fg2);padding:8px 18px;cursor:pointer;white-space:nowrap;margin-bottom:-1px}
.sheet-tab.on{background:var(--card);color:var(--fg);box-shadow:inset 0 3px 0 var(--accent)}
.sheet-tab:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.sheet{display:grid;gap:16px}.sheet[hidden]{display:none}
.sumsec .axis{border:0;padding:0;margin:0}
.hero-sub{font-size:16px;font-weight:600;color:var(--fg2)}
.tierchip{display:inline-block;border-radius:6px;padding:1px 10px;font-weight:700;background:var(--accent);color:#fff}
.rung{display:grid;grid-template-columns:90px 1fr auto;gap:10px;align-items:center;padding:8px 10px;border-radius:8px;border:1px solid var(--line);margin-bottom:6px}
.rung.cur{border-color:var(--accent)}.rung-name{font-size:14px}
.rung-cos{display:flex;gap:6px;flex-wrap:wrap}
.co{border:1px solid var(--line);border-radius:12px;padding:0 10px;font-size:12.5px;background:var(--card)}
.co.me{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:700}
.goal{font-size:12px;font-weight:700;color:var(--accent)}.goal.cur{color:var(--fg2)}
.motiv{border-color:var(--accent);box-shadow:inset 4px 0 0 var(--accent)}
.motiv ul{margin:4px 0 4px;padding-left:18px}.motiv li{margin:4px 0}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.rank{display:grid;grid-template-columns:max-content 1fr max-content;gap:6px 10px;align-items:center;font-size:13px}
.rank .track{height:14px;display:flex;align-items:center}
.rank .track>div{height:14px;border-radius:0 4px 4px 0;min-width:2px}
.rank .us{background:var(--accent)}.rank .other{background:var(--other)}
.me-t{font-weight:700;color:var(--fg)}
.hrow{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
h1{font-size:20px;margin:0}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1200px;margin:auto;padding:8px 16px 40px;display:grid;gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
h2{font-size:16px;margin:0 0 12px}h3{font-size:14px;margin:18px 0 8px}h4{font-size:13px;margin:0 0 8px;color:var(--fg2)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:24px;font-weight:650;line-height:1.2}.kpi span{color:var(--fg2);font-size:12px;display:block}.kpi small{color:var(--muted);font-size:11px}
.hero{font-size:52px;font-weight:650;line-height:1;margin:4px 0}
.sum{display:grid;grid-template-columns:minmax(260px,1fr) minmax(260px,1.4fr);gap:16px}
.card{border:1px solid var(--line);border-radius:8px;padding:12px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;margin-bottom:12px;align-items:start}
.sum .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
.axis{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-top:14px}
.axis-h{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.axis-h h3{margin:0;font-size:15px}.axis-h .muted{font-size:12px}
.axis-no{font-weight:700;color:var(--accent)}
.vrows{display:grid;grid-template-columns:max-content 1fr max-content;gap:10px 12px;align-items:center;font-size:13px}
.list{font-size:12.5px}.dl{margin-bottom:3px}
.tpl{font:inherit;font-size:11.5px;border:1px solid var(--line);background:var(--chip);color:var(--fg);border-radius:4px;padding:0 6px;margin-left:6px;cursor:pointer;white-space:nowrap}
.tpl:hover,.tpl:focus-visible{border-color:var(--accent)}
.tplgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px 12px}
.tplitem{display:flex;flex-direction:column;align-items:flex-start;gap:2px}.tplitem .tpl{margin-left:0;font-size:12.5px;padding:2px 8px}.why{display:block;min-width:130px;white-space:pre-line;font-size:12px;color:var(--fg2)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12px;white-space:nowrap}
.lv{display:inline-block;border-radius:4px;padding:0 7px;font-size:12px;font-weight:600;white-space:nowrap}
.lv.h{background:var(--critical);color:#fff}.lv.m{background:var(--warning);color:#0b0b0b}.lv.l{background:var(--good);color:#fff}
.ok{color:var(--good-text);font-weight:600}.bad{color:var(--bad-text);font-weight:600}.muted{color:var(--muted)}
.note{color:var(--note);font-size:12px;white-space:pre-line}
.chg{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-line}
.rule{font-size:12px;color:var(--muted);margin:0 0 8px}
select,input[type=search],.btn{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
input[type=search]{min-width:180px}.btn{cursor:pointer;padding:4px 12px}.btn:hover{border-color:var(--accent)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:16px 0 12px;flex-wrap:wrap}
.tab{font:inherit;background:none;border:0;border-bottom:2px solid transparent;padding:6px 10px;color:var(--muted);cursor:pointer}
.tab.on{color:var(--fg);border-bottom-color:var(--accent);font-weight:600}
.seg{display:flex;gap:2px;height:28px;margin:8px 0}
.seg>div{border-radius:4px;display:flex;align-items:center;padding:0 8px;font-size:12px;font-weight:600;white-space:nowrap;min-width:2px;outline-offset:2px}
.seg.thin{height:8px;margin:0;min-width:140px}.seg.thin>div{border-radius:4px;padding:0}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--fg2)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.meter{height:8px;background:var(--track);border-radius:4px;min-width:80px;outline-offset:2px}
.meter>div{height:100%;background:var(--accent);border-radius:4px}
.hbar{display:grid;grid-template-columns:minmax(120px,max-content) 1fr auto;gap:6px 10px;align-items:center;font-size:13px}
.hbar .track{height:14px;display:flex;align-items:center}
.hbar .track>div{height:14px;background:var(--accent);border-radius:0 4px 4px 0;min-width:2px}
.status{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:6px;padding:4px 10px;margin:0 8px 8px 0;font-size:13px}
.status b{font-variant-numeric:tabular-nums}
.exp{border:0;background:none;color:var(--accent);cursor:pointer;font:inherit;padding:0 4px}
tr.detail td{background:var(--bg)}
.orig{white-space:pre-wrap;font-size:12.5px;line-height:1.6;max-width:900px}
.orig b{display:block;margin-bottom:4px}
svg text{fill:var(--muted);font-size:11px}
.tip{position:fixed;display:none;pointer-events:none;z-index:10;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font-size:12px;box-shadow:0 4px 12px rgba(0,0,0,.15);max-width:320px}
footer{max-width:1200px;margin:auto;padding:0 16px 24px;color:var(--muted);font-size:12px}
@media (max-width:700px){.sum{grid-template-columns:1fr}.hero{font-size:44px}}
@media print{body{background:#fff;color:#000}.btn,.row,.tabs,.exp,.tip,.tpl,.sheets,.sheet[hidden]{display:none!important}
section{border:0;padding:0;overflow:visible}tr{break-inside:avoid}}
</style></head><body>
<header><div class="hrow"><div><h1>CompassPilot · CSP 파트너 등급 관리 대시보드</h1>
<p>Competency(AWS M&amp;M Assessment)와 임직원 자격, 파트너 등급의 두 축을 한 화면에서 봅니다. 생성: $generated</p></div>
<button class="btn" id="printbtn" type="button">인쇄</button></div></header>
<nav class="sheets" role="tablist" aria-label="시트">
<button type="button" role="tab" class="sheet-tab" id="tab-home" data-sheet="home">현주소</button>
<button type="button" role="tab" class="sheet-tab" id="tab-comp" data-sheet="comp">Competency</button>
<button type="button" role="tab" class="sheet-tab" id="tab-cert" data-sheet="cert">임직원 자격</button>
<button type="button" role="tab" class="sheet-tab" id="tab-eval" data-sheet="eval">자체 평가</button>
</nav>
<main>
<div class="sheet" id="sheet-home" role="tabpanel" aria-labelledby="tab-home">
<section id="home"></section>
</div>
<div class="sheet" id="sheet-comp" role="tabpanel" aria-labelledby="tab-comp" hidden>
<section id="summary" class="sumsec"></section>
<section id="ver"></section>
<section id="todo"></section>
</div>
<div class="sheet" id="sheet-cert" role="tabpanel" aria-labelledby="tab-cert" hidden>
<section id="summary2" class="sumsec"></section>
<section id="cert"></section>
</div>
<div class="sheet" id="sheet-eval" role="tabpanel" aria-labelledby="tab-eval" hidden>
<section id="eval"></section>
</div>
</main>
<div id="tip" class="tip" role="tooltip"></div>
<footer>사내 확인용. 자격 현황은 숫자 집계만 표시합니다(이름 없음). 원문·ID는 AWS 영문 그대로입니다. 막대에 마우스를 올리거나 Tab 키로 이동하면 값이 보입니다.</footer>
<script id="data" type="application/json">$data</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const SVG_NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else e.setAttribute(k, v); }
  for (const k of kids) e.append(k instanceof Node ? k : document.createTextNode(k ?? '')); return e; };
const svg = (tag, attrs = {}) => { const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v)); return e; };
const kpi = (v, label, sub) => el('div', {class: 'kpi'}, el('b', {}, String(v)), el('span', {}, label), sub ? el('small', {}, sub) : '');
const table = (heads, rows) => el('table', {}, el('thead', {}, el('tr', {}, ...heads.map(h => el('th', {}, h)))),
  el('tbody', {}, ...rows.map(r => el('tr', {}, ...r.map(c => el('td', {}, c))))));
const TYPE = {substantive: '실질 변경', minor_notation: '경미(표기)', minor_typo: '경미(오타)', added: '추가'};
const fmt = v => v == null ? '-' : (typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v));
const pct = r => r == null ? '-' : (r * 100).toFixed(1) + '%';
const changesText = cs => (cs || []).map(c => '"' + c.old + '" → "' + c.new + '"').join('\n');
const ok = x => x && !x.error ? x : null;
const noteSpan = n => el('span', {class: 'note'}, n ? '[내부 메모] ' + n : '');
const LV_CLASS = {'상': 'lv h', '중': 'lv m', '하': 'lv l'};
const lvChip = lv => lv ? el('span', {class: LV_CLASS[lv] || 'lv'}, lv) : '-';
// 탭·필터 상태는 버전을 바꿔도 유지한다
const STATE = {tab: 'prep', q: '', level: '', scope: '', orgLevel: 'by_team'};

// ── 툴팁: 마우스와 키보드(Tab) 모두에서 값을 보여 준다. 값은 표에도 있다(툴팁은 보조) ──
const TIP = document.getElementById('tip');
function hover(node, text) {
  node.setAttribute('tabindex', '0'); node.setAttribute('aria-label', text);
  const show = (x, y) => { if (!TIP) return; TIP.textContent = text; TIP.style.display = 'block';
    TIP.style.left = Math.min(x + 12, (window.innerWidth || 9999) - 340) + 'px'; TIP.style.top = (y + 14) + 'px'; };
  const hide = () => { if (TIP) TIP.style.display = 'none'; };
  node.addEventListener('pointermove', e => show(e.clientX, e.clientY));
  node.addEventListener('pointerleave', hide);
  node.addEventListener('focus', () => { const r = node.getBoundingClientRect ? node.getBoundingClientRect() : {left: 0, bottom: 0}; show(r.left, r.bottom); });
  node.addEventListener('blur', hide);
  return node;
}

// ── 도식 부품 ──
const C = {ready: 'var(--good)', partial: 'var(--warning)', none: 'var(--critical)'};
const DARK_INK = '#0b0b0b';
function segBar(parts, label, thin) {
  const total = parts.reduce((s, p) => s + p.value, 0);
  const bar = el('div', {class: 'seg' + (thin ? ' thin' : ''), role: 'img',
    'aria-label': label + ': ' + parts.map(p => p.name + ' ' + p.value).join(', ')});
  for (const p of parts) {
    if (!p.value) continue;
    const share = total ? p.value / total : 0;
    const b = el('div', {style: 'flex:' + p.value + ' 1 0;background:' + p.color + ';color:' + (p.ink || '#fff')},
      !thin && share >= 0.08 ? String(p.value) : '');
    hover(b, p.value + (p.unit || '개') + ' · ' + p.name + ' (' + Math.round(share * 100) + '%)');
    bar.append(b);
  }
  return bar;
}
const legend = parts => el('div', {class: 'legend'}, ...parts.map(p => el('span', {}, el('i', {style: 'background:' + p.color}), p.name)));
const readyParts = (r, p, n, unit) => [{name: '준비완료', value: r, color: C.ready, unit}, {name: '일부', value: p, color: C.partial, ink: DARK_INK, unit},
  {name: '미준비', value: n, color: C.none, unit}];
function meter(rate, label) {
  const m = el('div', {class: 'meter', role: 'img'}, el('div', {style: 'width:' + Math.round((rate || 0) * 100) + '%'}));
  return hover(m, label);
}
function statusChip(n, name, good, unit) {
  const isOk = good ? n === 0 : true;
  return el('span', {class: 'status'}, el('span', {class: isOk ? 'ok' : 'bad', 'aria-hidden': 'true'}, isOk ? (good ? '✓' : 'ⓘ') : '⚠'),
    name, el('b', {}, n + (unit || '건')));
}
function countBy(items, key) { const c = {}; for (const i of items) c[i[key]] = (c[i[key]] || 0) + 1; return c; }

const MONTHS = ['january','february','march','april','may','june','july','august','september','october','november','december'];
function validityEnd(text) {  // "August 2026 - February 2027" → 2027-02-28
  const part = String(text || '').split('-').pop().trim().toLowerCase().split(/\s+/);
  const m = MONTHS.indexOf(part[0]), y = parseInt(part[1], 10);
  return m >= 0 && y ? new Date(y, m + 1, 0) : null;
}
const ymd = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

// ── 한눈 요약 (최신 버전 기준) ──
function renderSummary() {
  // 시트마다 맨 위에 그 축의 한눈 요약을 둔다 (Competency 시트: #summary, 임직원 자격 시트: #summary2)
  const box = document.getElementById('summary'); box.replaceChildren();
  const certBox = document.getElementById('summary2'); certBox.replaceChildren();
  renderCertSummary(certBox);
  const V = D.versions; if (!V.latest) { box.append(el('p', {class: 'muted'}, '데이터 없음')); return; }
  const v = V.versions[V.latest], df = ok(v.difficulty), dv = ok(v.deliverables), d = v.diff;
  // ── Competency 준비 ──
  const comp = axisBlock('', 'Competency 한눈 요약', 'AWS M&M · ' + V.latest + ' 판(최신) · 준비 상태는 가상 데이터');
  const left = el('div', {class: 'card'});
  if (df) {
    const rc = countBy(df.items, 'readiness'), r = rc['준비완료'] || 0, p = rc['일부'] || 0, n = rc['미준비'] || 0, all = r + p + n;
    const parts = readyParts(r, p, n);
    left.append(el('h4', {}, '준비완료 비율'), el('div', {class: 'hero'}, Math.round(r / all * 100) + '%'),
      el('div', {class: 'muted'}, '요구사항 ' + all + '개 중 준비완료 ' + r + ' · 일부 ' + p + ' · 미준비 ' + n),
      segBar(parts, '준비 상태'), legend(parts));
  } else left.append(el('p', {class: 'muted'}, '준비 상태 데이터 없음'));
  const tiles = el('div', {class: 'kpis'});
  const end = validityEnd(v.validity);
  if (end) { const today = new Date(); today.setHours(0, 0, 0, 0);
    const days = Math.ceil((end - today) / 86400000);
    tiles.append(kpi(days >= 0 ? 'D-' + days : '종료', '유효기간 종료까지', ymd(end))); }
  if (d) tiles.append(kpi(d.added.length + d.removed.length + d.changed.length + d.sheet_notes.length, '이번 버전 변경',
    '추가 ' + d.added.length + ' · 변경 ' + d.changed.length + ' · 안내문 ' + d.sheet_notes.length));
  if (df) tiles.append(kpi(df.counts.high, '난이도 상', '3~4점 · 먼저 착수'));
  if (dv) tiles.append(kpi(dv.total, '준비할 산출물', '양식 연결 ' + (dv.linked || 0) + '개 · 고객 사례 항목 ' + dv.customer + '개'));
  comp.append(el('div', {class: 'sum'}, left, el('div', {}, tiles)));
  box.append(comp);
  if (df) {
    const byDel = Object.fromEntries((dv ? dv.items : []).map(i => [i.id, i]));
    const top = df.items.filter(i => i.readiness !== '준비완료').slice(0, 5);
    const go = el('button', {class: 'btn', type: 'button'}, '난이도 상 전체 보기');
    go.addEventListener('click', () => { STATE.tab = 'prep'; STATE.level = '상'; STATE.q = ''; STATE.scope = '';
      renderVersions(); goSheet('comp', 'ver'); });
    comp.append(el('h4', {style: 'margin-top:16px'}, '우선 준비 항목 (점수 높은 순, 준비완료 제외)'),
      table(['난이도', '점수', 'ID', '제목', '준비 상태', '산출물'], top.map(i => [lvChip(i.level), String(i.score), i.id, i.title,
        i.readiness, byDel[i.id] ? byDel[i.id].deliverables.length + '개' : '-'])),
      el('div', {class: 'row', style: 'margin:8px 0 0'}, go));
  }

}

function renderCertSummary(box) {
  // ── 임직원 자격 ──
  const cert = axisBlock('', '임직원 자격 한눈 요약', '취득 대상 대비 실적 · 가상 데이터 · 숫자만(이름 없음)');
  const T = D.certs && ok(D.certs.targets);
  if (!T) { cert.append(el('p', {class: 'muted'}, '자격 대상 데이터 없음')); box.append(cert); return; }
  const P = T.by_person;
  const pparts = [{name: '전부 취득', value: P.all, color: C.ready, unit: '명'}, {name: '일부 취득', value: P.partial, color: C.partial, ink: DARK_INK, unit: '명'},
    {name: '미취득 (0건)', value: P.none, color: C.none, unit: '명'}];
  const cleft = el('div', {class: 'card'}, el('h4', {}, '자격 취득률 (연인원)'), el('div', {class: 'hero'}, pct(T.total.rate)),
    el('div', {class: 'muted'}, '대상 ' + T.total.target + '건 중 취득 ' + T.total.achieved + '건 · 아래는 사람 기준(대상 인원 ' + P.people + '명)'),
    segBar(pparts, '사람별 취득 현황'), legend(pparts));
  const vrows = el('div', {class: 'vrows'});
  for (const v of T.vendors) { const x = T.by_vendor[v];
    vrows.append(el('span', {}, v), meter(x.rate, pct(x.rate) + ' · ' + v + ' 취득 ' + x.achieved + ' / 대상 ' + x.target),
      el('span', {class: 'muted'}, pct(x.rate) + ' (' + x.achieved + '/' + x.target + ')')); }
  const K = T.checks, errs = K.unknown_employee_ids + K.duplicate_rows;
  const goCert = el('button', {class: 'btn', type: 'button'}, '조직별·점검 상세 보기');
  goCert.addEventListener('click', () => goSheet('cert', 'cert'));
  const cright = el('div', {class: 'card'}, el('h4', {}, '벤더별 취득률'), vrows,
    el('div', {style: 'margin-top:12px'}, statusChip(errs, '데이터 점검 오류', true), statusChip(P.none, '미취득 인원', true, '명')),
    el('div', {class: 'row', style: 'margin:4px 0 0'}, goCert));
  cert.append(el('div', {class: 'sum'}, cleft, cright));
  box.append(cert);
}

function axisBlock(no, title, sub) {
  return el('div', {class: 'axis'}, el('div', {class: 'axis-h'}, el('span', {class: 'axis-no'}, no), el('h3', {}, title),
    el('span', {class: 'muted'}, sub)));
}

// ── ① Competency 버전 ──
function renderVersions() {
  const box = document.getElementById('ver'); box.replaceChildren(el('h2', {}, 'Assessment 버전별 상세'));
  const V = D.versions; if (!V.latest) { box.append(el('p', {class: 'muted'}, '데이터 없음')); return; }
  const sel = el('select', {id: 'vsel'}, ...V.labels.slice().reverse().map(l => el('option', {value: l}, l + ' 판')));
  box.append(el('div', {class: 'row'}, el('label', {for: 'vsel'}, '버전 선택'), sel,
    el('span', {class: 'muted'}, '등록 버전 ' + V.labels.length + '개 · 새 버전은 data/private/versions/에 넣고 색인 명령 실행')));
  const body = el('div'); box.append(body);
  const draw = label => {
    const v = V.versions[label], d = v.diff, df = ok(v.difficulty), dv = ok(v.deliverables); body.replaceChildren();
    const nChanges = d ? d.added.length + d.removed.length + d.changed.length + d.sheet_notes.length : 0;
    const k = el('div', {class: 'kpis'}, kpi(v.total, '요구사항', '유효기간 ' + (v.validity || '-')));
    if (d) k.append(kpi(nChanges, '직전 버전 대비 변경', d.from + ' → ' + label));
    if (df) k.append(kpi(df.counts.high, '난이도 상'));
    if (dv) k.append(kpi(dv.total, '산출물'));
    body.append(k);
    const TABS = [['changes', d ? '변경 내역 (' + nChanges + ')' : '변경 내역'], ['prep', '준비 현황 (난이도·산출물)'],
                  ['all', '요구사항 전체 (' + v.total + ')']];
    const pane = el('div');
    const buttons = TABS.map(([key, name]) => { const b = el('button', {class: 'tab', type: 'button', 'data-tab': key}, name);
      b.addEventListener('click', () => { STATE.tab = key; show(); }); return b; });
    body.append(el('div', {class: 'tabs', role: 'tablist'}, ...buttons), pane);
    const show = () => {
      for (const b of buttons) b.className = 'tab' + (b.getAttribute('data-tab') === STATE.tab ? ' on' : '');
      pane.replaceChildren();
      if (STATE.tab === 'changes') drawChanges(pane, v, label);
      else if (STATE.tab === 'prep') drawPrep(pane, v, df, dv, label);
      else drawAll(pane, v);
    };
    show();
  };
  sel.addEventListener('change', () => draw(sel.value)); draw(V.latest);
}

function filterBar(pane, opts, redraw) {
  const q = el('input', {type: 'search', placeholder: 'ID·제목 검색', 'aria-label': 'ID·제목 검색'}); q.value = STATE.q;
  q.addEventListener('input', () => { STATE.q = q.value; redraw(); });
  const kids = [q];
  if (opts.level) {
    const s = el('select', {'aria-label': '난이도'}, ...[['', '난이도 전체'], ['상', '상'], ['중', '중'], ['하', '하']]
      .map(([val, t]) => el('option', {value: val}, t)));
    s.value = STATE.level; s.addEventListener('change', () => { STATE.level = s.value; redraw(); }); kids.push(s);
  }
  const sc = el('select', {'aria-label': '범위'}, ...[['', '범위 전체'], ['회사 차원', '회사 차원'], ['고객 사례 4건', '고객 사례 4건']]
    .map(([val, t]) => el('option', {value: val}, t)));
  sc.value = STATE.scope; sc.addEventListener('change', () => { STATE.scope = sc.value; redraw(); }); kids.push(sc);
  const count = el('span', {class: 'muted'});
  kids.push(count);
  if (opts.extra) kids.push(...opts.extra);
  pane.append(el('div', {class: 'row'}, ...kids));
  return count;
}
const matchQ = r => { const q = STATE.q.trim().toLowerCase(); return !q || r.id.toLowerCase().includes(q) || r.title.toLowerCase().includes(q); };

// 행 앞의 ▸ 버튼을 누르면 AWS 원문이 펼쳐지는 표 (B3)
function expTable(heads, rows) {
  const ncol = heads.length + 1, tbody = el('tbody');
  for (const r of rows) {
    const btn = el('button', {class: 'exp', type: 'button', 'aria-expanded': 'false', 'aria-label': r.req.id + ' 원문 펼치기'}, '▸');
    const tr = el('tr', {}, el('td', {}, btn), ...r.cells.map(c => el('td', {}, c)));
    let det = null;
    btn.addEventListener('click', () => {
      if (det) { det.remove(); det = null; btn.textContent = '▸'; btn.setAttribute('aria-expanded', 'false'); return; }
      det = el('tr', {class: 'detail'}, el('td', {colspan: String(ncol)},
        el('div', {class: 'orig'}, el('b', {}, 'AWS 원문 · ' + r.req.id), r.req.text || '(원문 없음)')));
      tr.after(det); btn.textContent = '▾'; btn.setAttribute('aria-expanded', 'true');
    });
    tbody.append(tr);
  }
  return el('table', {}, el('thead', {}, el('tr', {}, el('th', {}, ''), ...heads.map(h => el('th', {}, h)))), tbody);
}

function drawChanges(pane, v, label) {
  const d = v.diff;
  if (!d) { pane.append(el('p', {class: 'muted'}, '첫 등록 버전이라 비교 대상이 없습니다.')); return; }
  const minor = d.changed.filter(c => c.type !== 'substantive').length;
  const parts = [{name: '추가', value: d.added.length, color: 'var(--s1)'}, {name: '실질 변경', value: d.changed.length - minor, color: 'var(--s2)'},
    {name: '경미 변경', value: minor, color: 'var(--s3)'}, {name: '안내문 변경', value: d.sheet_notes.length, color: 'var(--s4)', ink: DARK_INK},
    {name: '삭제', value: d.removed.length, color: 'var(--critical)'}];
  pane.append(el('h4', {}, d.from + ' → ' + label + ' 변경 구성'), segBar(parts, '변경 구성'), legend(parts.filter(p => p.value)),
    el('p', {class: 'rule', style: 'margin-top:8px'}, '실질 변경 = 의미가 바뀜, 경미(표기) = 대소문자·문장부호만, 경미(오타) = 철자만 (파이썬 규칙)'));
  const rows = [
    ...d.added.map(a => [el('span', {class: 'chip'}, '추가'), a.id, a.title, '', noteSpan(a.note)]),
    ...d.removed.map(r => [el('span', {class: 'chip'}, '삭제'), r.id, r.title, '', '']),
    ...d.changed.map(c => [el('span', {class: 'chip'}, TYPE[c.type] || c.type), c.id, c.title,
      el('span', {class: 'chg'}, changesText(c.changes)), noteSpan(c.note)]),
    ...d.sheet_notes.map(n => [el('span', {class: 'chip'}, '안내문 ' + (TYPE[n.type] || n.type)), '(시트 안내문)', n.sheet,
      el('span', {class: 'chg'}, changesText(n.changes)), '']),
  ];
  pane.append(table(['구분', 'ID', '제목', '바뀐 부분', '내부 메모'], rows));
}

function csvCell(x) { const s = String(x == null ? '' : x); return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; }
function prepCsv(rows) {  // 엑셀에서 한글이 깨지지 않게 BOM을 붙인다
  const head = ['난이도', '점수', 'ID', '제목', '범위', '준비 상태', '준비 범위', '산출물', '양식', '점수 근거'];
  const tplNames = x => x && x.templates ? [...new Set(x.templates.filter(t => t && TPL[t]).map(t => TPL[t].title))].join(' / ') : '';
  const body = rows.map(r => [r.d ? r.d.level : '', r.d ? r.d.score : '', r.id, r.title, r.scope, r.d ? r.d.readiness : '',
    r.x ? r.x.cases : '', r.x ? r.x.deliverables.join(' / ') : '', tplNames(r.x), r.d ? r.d.reasons.join(' / ') : '']);
  return '﻿' + [head, ...body].map(a => a.map(csvCell).join(',')).join('\r\n');
}
function download(name, data, mime) {
  try {
    const url = URL.createObjectURL(new Blob([data], {type: mime || 'text/csv;charset=utf-8'}));
    const a = el('a', {href: url, download: name}); document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { alert('내보내기에 실패했습니다: ' + e); }
}

// ── 산출물 양식: HTML 안에 넣은 파일(base64)을 눌러서 내려받는다 ──
const TPL = D.templates || {};
function b64bytes(b64) { const s = atob(b64); const a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a; }
function tplButton(id, label) {
  const t = TPL[id]; if (!t) return '';
  const b = el('button', {class: 'tpl', type: 'button', title: t.title + ' 양식 내려받기 (' + t.file + ')',
    'aria-label': t.title + ' 양식 내려받기'}, label || '📎 양식');
  b.addEventListener('click', () => download(t.file, b64bytes(t.b64), t.mime));
  return b;
}
function delivCell(x) {
  if (!x) return '-';
  return el('div', {class: 'list'}, ...x.deliverables.map((n, i) =>
    el('div', {class: 'dl'}, '☐ ' + n, x.templates && x.templates[i] ? tplButton(x.templates[i]) : '')));
}

function drawPrep(pane, v, df, dv, label) {
  if (!df && !dv) { pane.append(el('p', {class: 'muted'}, '데이터 없음 (난이도·산출물)')); return; }
  const byDiff = Object.fromEntries((df ? df.items : []).map(i => [i.id, i]));
  const byDel = Object.fromEntries((dv ? dv.items : []).map(i => [i.id, i]));
  const rowsAll = v.requirements.map(r => ({...r, d: byDiff[r.id], x: byDel[r.id]}))
    .sort((a, b) => ((b.d ? b.d.score : -1) - (a.d ? a.d.score : -1)) || a.id.localeCompare(b.id));
  // 도식: 난이도 분포 + 영역별 준비 상태
  const charts = el('div', {class: 'grid2'});
  if (df) {
    const parts = [{name: '상 (3~4점)', value: df.counts.high, color: C.none}, {name: '중 (2점)', value: df.counts.medium, color: C.partial, ink: DARK_INK},
      {name: '하 (0~1점)', value: df.counts.low, color: C.ready}];
    charts.append(el('div', {class: 'card'}, el('h4', {}, '난이도 분포'), segBar(parts, '난이도 분포'), legend(parts),
      el('p', {class: 'rule', style: 'margin-top:8px'}, '점수: 미준비 +2 · 일부 +1 · 고객 사례 4건 증빙 항목 +1 · 이번 버전 신규 +1')));
    const areas = [];
    for (const r of rowsAll.slice().sort((a, b) => a.sheet.localeCompare(b.sheet) || a.area.localeCompare(b.area))) {
      const key = r.area || r.sheet; let a = areas.find(x => x.key === key);
      if (!a) { a = {key, r: 0, p: 0, n: 0}; areas.push(a); }
      const s = r.d ? r.d.readiness : '미준비'; if (s === '준비완료') a.r++; else if (s === '일부') a.p++; else a.n++;
    }
    areas.sort((a, b) => (a.r / (a.r + a.p + a.n)) - (b.r / (b.r + b.p + b.n)) || a.key.localeCompare(b.key));
    const aparts = readyParts(0, 0, 0);
    charts.append(el('div', {class: 'card'}, el('h4', {}, '영역별 준비 상태 (준비 비율 낮은 순)'), legend(aparts),
      table(['영역', '준비 상태', '준비완료'], areas.map(a => [a.key, segBar(readyParts(a.r, a.p, a.n), a.key, true),
        el('span', {class: 'muted'}, a.r + ' / ' + (a.r + a.p + a.n))]))));
  }
  pane.append(charts);
  const tids = Object.keys(TPL);
  if (tids.length) {
    const used = {};
    for (const r of rowsAll) if (r.x && r.x.templates) for (const t of r.x.templates) if (t) used[t] = (used[t] || 0) + 1;
    pane.append(el('div', {class: 'card', style: 'margin-bottom:12px'},
      el('h4', {}, '산출물 양식 모음 (' + tids.length + '종' + (dv ? ' · 산출물 ' + dv.total + '개 중 ' + dv.linked + '개 연결' : '') + ')'),
      el('p', {class: 'rule'}, '가상 양식(Markdown·CSV)입니다. 📎를 누르면 내려받습니다. 아래 체크리스트에서도 산출물 옆 📎로 받을 수 있습니다. 실제 사내 양식은 파일만 바꿔 넣으면 됩니다.'),
      el('div', {class: 'tplgrid'}, ...tids.map(id => el('div', {class: 'tplitem'}, tplButton(id, '📎 ' + TPL[id].title),
        el('small', {class: 'muted'}, TPL[id].file + ' · 산출물 ' + (used[id] || 0) + '개'))))));
  }
  pane.append(el('p', {class: 'rule'}, '준비 상태는 data/sample/readiness.csv(가상 데이터), 산출물은 색인할 때 원문에서 한 번 추출한 결과(근거 문장 원문 대조)입니다. ▸를 누르면 AWS 원문이 펼쳐집니다.'));
  if (!df) pane.append(el('p', {class: 'muted'}, '난이도 데이터 없음' + (v.difficulty && v.difficulty.error ? ' (' + v.difficulty.error + ')' : '')));
  if (!dv) pane.append(el('p', {class: 'muted'}, '산출물 데이터 없음' + (v.deliverables && v.deliverables.error ? ' (' + v.deliverables.error + ')' : '')));
  let current = rowsAll;
  const csvBtn = el('button', {class: 'btn', type: 'button'}, 'CSV 내보내기');
  csvBtn.addEventListener('click', () => download('CompassPilot_준비현황_' + label + '.csv', prepCsv(current)));
  const printBtn = el('button', {class: 'btn', type: 'button'}, '인쇄');
  printBtn.addEventListener('click', () => window.print());
  const count = filterBar(pane, {level: !!df, extra: [csvBtn, printBtn]}, () => redraw());
  const holder = el('div'); pane.append(holder);
  const redraw = () => {
    current = rowsAll.filter(r => matchQ(r) && (!STATE.scope || r.scope === STATE.scope)
      && (!STATE.level || (r.d && r.d.level === STATE.level)));
    count.textContent = current.length + '개 표시 / 전체 ' + rowsAll.length + '개';
    holder.replaceChildren(expTable(['난이도', '점수', 'ID', '제목', '준비 상태', '준비 범위', '산출물 체크리스트', '점수 근거'], current.map(r => ({req: r, cells: [
      r.d ? lvChip(r.d.level) : '-', r.d ? String(r.d.score) : '-', r.id, r.title,
      r.d ? r.d.readiness : '-', r.x ? r.x.cases : '-',
      delivCell(r.x),
      el('span', {class: 'why'}, r.d ? r.d.reasons.join('\n') : '-')]}))));
  };
  redraw();
}

function drawAll(pane, v) {
  const count = filterBar(pane, {level: false}, () => redraw());
  const holder = el('div'); pane.append(holder);
  const redraw = () => {
    const rows = v.requirements.filter(r => matchQ(r) && (!STATE.scope || r.scope === STATE.scope));
    count.textContent = rows.length + '개 표시 / 전체 ' + v.requirements.length + '개';
    holder.replaceChildren(expTable(['ID', '제목', '시트', '영역', '범위', '내부 메모'],
      rows.map(r => ({req: r, cells: [r.id, r.title, r.sheet, r.area, r.scope, el('span', {class: 'note'}, r.note)]}))));
  };
  redraw();
}

// ── ② 임직원 자격 ──
function renderCerts() {
  const box = document.getElementById('cert'); box.replaceChildren(el('h2', {}, '임직원 자격 상세 (숫자만, 가상 데이터)'));
  const CE = D.certs; if (!CE) { box.append(el('p', {class: 'muted'}, '데이터 없음')); return; }
  const T = ok(CE.targets);
  if (T) drawTargets(box, T);
  else box.append(el('p', {class: 'muted'}, '대상 데이터 없음' + (CE.targets && CE.targets.error ? ' (' + CE.targets.error + ')' : '')));

  box.append(el('h3', {}, '보유 자격 (대상 여부와 무관한 전체 보유)'));
  box.append(el('div', {class: 'kpis'}, kpi(CE.total, '자격 건수'), kpi(CE.employees, '보유 인원'),
    ...Object.entries(CE.by_vendor).map(([v, n]) => kpi(n, v))));
  const max = Math.max(...CE.by_cert.map(x => x[1]));
  const bars = el('div', {class: 'hbar', role: 'img', 'aria-label': '자격증별 건수'});
  for (const [c, n] of CE.by_cert) {
    const t = el('div', {class: 'track'}, el('div', {style: 'width:' + Math.max(1, Math.round(100 * n / max)) + '%'}));
    bars.append(el('span', {}, c), hover(t, n + '건 · ' + c), el('span', {class: 'muted'}, n + '건'));
  }
  box.append(el('h4', {style: 'margin-top:12px'}, '자격증별 건수'), bars);
  box.append(el('h4', {style: 'margin-top:16px'}, '사업부 × 벤더 (보유 건수)'),
    table(['사업부', ...CE.vendors], CE.divisions.map((d, i) => [d, ...CE.matrix[i].map(String)])));
  box.append(el('p', {class: 'rule', style: 'margin-top:8px'}, '명단(이름)은 CLI에서 권한별로만 조회됩니다: 인사팀 전사 · 담당 사업부 · 팀장 팀 · 그룹장 그룹.'));
}

function drawTargets(box, T) {
  const P = T.by_person;
  box.append(el('p', {class: 'rule'}, '취득 대상(data/sample/cert_targets.csv) 대비 실적입니다. 대상 벤더의 자격을 1건 이상 보유하면 취득으로 봅니다. 벤더별은 연인원, 사람별은 실인원 기준입니다. (참고) 2개 이상 벤더 대상자 ' + P.multi_vendor + '명.'));
  // 벤더별·사람별 현황은 시트 맨 위 한눈 요약에 있으므로 상세 칸에서는 반복하지 않는다

  const LEVELS = [['by_division', '사업부'], ['by_team', '팀'], ['by_group', '그룹']];
  const lv = el('select', {'aria-label': '조직 단위'}, ...LEVELS.map(([k, n]) => el('option', {value: k}, n + '별')));
  lv.value = STATE.orgLevel;
  const holder = el('div');
  const drawOrg = () => {
    const depth = LEVELS.findIndex(([k]) => k === lv.value) + 1;
    const heads = ['사업부', '팀', '그룹'].slice(0, depth);
    holder.replaceChildren(table([...heads, '대상 인원', ...T.vendors.map(v => v + ' 취득/대상'), '취득률', ''],
      T[lv.value].map(r => [...r.org, String(r.people),
        ...T.vendors.map(v => r.vendors[v].target ? r.vendors[v].achieved + ' / ' + r.vendors[v].target : '-'),
        pct(r.rate), meter(r.rate, pct(r.rate) + ' · ' + r.org.join(' ') + ' 취득 ' + r.achieved + ' / 대상 ' + r.target)])));
  };
  lv.addEventListener('change', () => { STATE.orgLevel = lv.value; drawOrg(); });
  box.append(el('h3', {}, '조직별 취득 현황'), el('div', {class: 'row'}, el('label', {}, '조직 단위'), lv), holder);
  drawOrg();

  const K = T.checks;
  box.append(el('h3', {}, '데이터 점검'), el('div', {},
    statusChip(K.unknown_employee_ids, '조직도에 없는 사번', true), statusChip(K.duplicate_rows, '중복 입력 행', true),
    statusChip(K.holders_not_target, '대상이 아닌데 보유 (참고)', false)),
  el('p', {class: 'rule'}, '앞의 두 항목은 0이어야 정상이며 집계에서 제외했습니다. 세 번째는 대상 목록 누락인지 확인할 참고 항목입니다.'));
}

// ── ③ 자체 평가 ──
function lineChart(points, label) {  // points: [{x: 라운드, y: 0~1, tip}]
  const W = 640, H = 190, L = 40, R = 48, Tp = 14, B = 28;
  const ys = points.map(p => p.y), lo = Math.min(0.8, Math.floor(Math.min(...ys) * 10) / 10), hi = 1;
  const X = i => L + (points.length === 1 ? 0 : i * (W - L - R) / (points.length - 1));
  const Y = y => Tp + (hi - y) / (hi - lo) * (H - Tp - B);
  const s = svg('svg', {viewBox: '0 0 ' + W + ' ' + H, width: '100%', role: 'img', 'aria-label': label, style: 'max-width:720px'});
  for (let t = lo; t <= hi + 1e-9; t += (hi - lo) / 2) {
    s.append(svg('line', {x1: L, x2: W - R, y1: Y(t), y2: Y(t), stroke: 'var(--line)', 'stroke-width': 1}));
    const tx = svg('text', {x: L - 6, y: Y(t) + 4, 'text-anchor': 'end'}); tx.textContent = Math.round(t * 100) + '%'; s.append(tx);
  }
  points.forEach((p, i) => { const tx = svg('text', {x: X(i), y: H - 8, 'text-anchor': 'middle'}); tx.textContent = 'R' + p.x; s.append(tx); });
  s.append(svg('path', {d: points.map((p, i) => (i ? 'L' : 'M') + X(i) + ' ' + Y(p.y)).join(' '), fill: 'none',
    stroke: 'var(--accent)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}));
  const step = points.length > 1 ? (W - L - R) / (points.length - 1) : 40;
  points.forEach((p, i) => {
    s.append(svg('circle', {cx: X(i), cy: Y(p.y), r: 4, fill: 'var(--accent)', stroke: 'var(--card)', 'stroke-width': 2}));
    s.append(hover(svg('rect', {x: X(i) - step / 2, y: Tp, width: step, height: H - Tp - B, fill: 'transparent'}), p.tip));
  });
  const last = points[points.length - 1];
  const end = svg('text', {x: X(points.length - 1) + 8, y: Y(last.y) + 4}); end.textContent = Math.round(last.y * 100) + '%'; end.setAttribute('style', 'fill:var(--fg)'); s.append(end);
  return s;
}

function renderEval() {
  const box = document.getElementById('eval'); box.replaceChildren(el('h2', {}, '자체 평가 결과'));
  const E = D.eval; if (!E) { box.append(el('p', {class: 'muted'}, '데이터 없음 (python -m evaluation.run_eval --round N)')); return; }
  const s = E.summary;
  const tab = document.getElementById('tab-eval'); if (tab) tab.textContent = '자체 평가 (' + s.passed + '/' + s.total + ')';
  box.append(el('p', {class: 'muted'}, '최신 라운드 ' + E.round + ' · ' + (E.run_at || '') + ' · ' + ((E.model || {}).chat || '')));
  box.append(el('div', {class: 'kpis'}, kpi(s.passed + '/' + s.total, '규칙 판정 통과'), kpi(fmt(s.judge_mean_score), 'LLM judge 평균(1~5)'),
    ...Object.entries(s.ragas_mean || {}).map(([m, v]) => kpi(fmt(v), m))));
  box.append(el('h3', {}, '성공 기준'), el('div', {}, ...Object.entries(s.criteria).map(([k, v]) =>
    el('span', {class: 'status'}, el('span', {class: v.met ? 'ok' : 'bad', 'aria-hidden': 'true'}, v.met ? '✓' : '⚠'), k, el('b', {}, String(v.value))))));
  const pts = E.history.map(h => ({x: h.round, y: h.total ? h.passed / h.total : 0,
    tip: '라운드 ' + h.round + ' · ' + h.passed + '/' + h.total + ' (' + pct(h.total ? h.passed / h.total : 0) + ') · judge ' + fmt(h.judge)}));
  if (pts.length) box.append(el('h3', {}, '라운드별 규칙 판정 통과율'), lineChart(pts, '라운드별 통과율'));
  box.append(el('h3', {}, '라운드별 추이 (표)'), table(['라운드', '통과', 'judge', 'faithfulness'],
    E.history.map(h => [String(h.round), h.passed + '/' + h.total, fmt(h.judge), fmt(h.faithfulness)])));
  box.append(el('h3', {}, '문항별 결과'), table(['#', '유형', '사용자', '질문', '결과', '판정', 'judge', 'faith'],
    E.items.map(i => [String(i.id), i.type, i.user, i.question, el('span', {class: i.passed ? 'ok' : 'bad'}, i.passed ? '✓ 통과' : '⚠ 실패'),
      i.detail, fmt(i.judge), fmt(i.faith)])));
}

function renderTodo() {
  const box = document.getElementById('todo');
  if (!D.not_implemented.length) { box.remove ? box.remove() : box.replaceChildren(); return; }
  box.replaceChildren(el('h2', {}, '④ 준비 중'));
  box.append(el('p', {class: 'muted'}, '미구현: ' + D.not_implemented.join(', ')));
}
// ── 현주소 시트 (첫 화면): 우리 회사 vs 익명 A사~E사(가상 수치). 순위·격차·전망은 파이썬이 계산한 값을 보여만 준다 ──
function renderHome() {
  const box = document.getElementById('home'); box.replaceChildren();
  box.append(el('div', {class: 'axis-h'}, el('h2', {style: 'margin:0'}, '우리 회사 현주소 · AWS 파트너 등급'),
    el('span', {class: 'muted'}, '국내 대형 SI·IT서비스 5개 사(익명)와 비교 · 수치와 등급 기준은 모두 가상')));
  const B = D.benchmark && ok(D.benchmark);
  if (!B) { box.append(el('p', {class: 'muted'}, '데이터 없음' + (D.benchmark && D.benchmark.error ? ' (' + D.benchmark.error + ')' : ''))); return; }
  const us = B.us, nt = B.next_tier, P = B.projection, M = Object.fromEntries(B.metrics.map(m => [m.metric, m]));

  // 1) 종합 순위 + 등급 사다리
  const left = el('div', {class: 'card'}, el('h4', {}, '종합 순위 (등급 → Competency 수 → 자격 인원 순)'),
    el('div', {class: 'hero'}, B.overall_rank + '위', el('span', {class: 'hero-sub'}, ' / ' + B.companies + '개 사' + (B.tied ? ' (공동)' : ''))),
    el('div', {}, '현재 등급 ', el('span', {class: 'tierchip'}, 'AWS ' + us.tier)));
  if (B.nearest_above) { const g = B.nearest_above;
    left.append(el('p', {class: 'muted', style: 'margin:8px 0 0'}, '바로 위 ' + g.company + '(' + g.tier + ')와 격차: Competency ' + g.competencies +
      '개 · 자격 인원 ' + g.certified_people + '명 · 고객 사례 ' + g.launches + '건')); }
  const ladder = el('div', {class: 'card'}, el('h4', {}, '등급 사다리'));
  for (const t of B.tiers.slice().reverse()) {
    const isNext = nt && t.tier === nt.tier, isCur = t.tier === us.tier;
    ladder.append(el('div', {class: 'rung' + (isCur ? ' cur' : '')},
      el('b', {class: 'rung-name'}, t.tier), el('div', {class: 'rung-cos'},
        ...(t.companies.length ? t.companies.map(c => el('span', {class: 'co' + (c === us.company ? ' me' : '')}, c)) : [el('span', {class: 'muted'}, '-')])),
      isNext ? el('span', {class: 'goal'}, '다음 목표') : (isCur ? el('span', {class: 'goal cur'}, '현재') : '')));
  }
  box.append(el('div', {class: 'sum'}, left, ladder));

  // 2) 다음 등급 조건 + 3) 취득하면 이렇게 바뀐다
  const row2 = el('div', {class: 'sum', style: 'margin-top:16px'});
  if (nt) {
    const c = el('div', {class: 'card'}, el('h4', {}, '다음 등급 ' + nt.tier + '까지 (조건 ' + nt.conditions.filter(x => x.met).length + '/' + nt.conditions.length + ' 충족)'));
    const g = el('div', {class: 'vrows'});
    for (const x of nt.conditions) {
      const rate = Math.min(1, x.current / x.required);
      g.append(el('span', {}, x.label), meter(rate, x.label + ' ' + x.current + ' / 기준 ' + x.required + x.unit),
        el('span', {class: x.met ? 'ok' : 'bad'}, x.current + ' / ' + x.required + x.unit + (x.met ? ' ✓ 충족' : ' · ' + x.gap + x.unit + ' 부족')));
    }
    c.append(g); row2.append(c);
  } else row2.append(el('div', {class: 'card'}, el('h4', {}, '최고 등급입니다'), el('p', {class: 'muted'}, '등급 유지 조건을 지켜 주세요.')));
  if (P) {
    const pm = P.next_tier ? P.next_tier.conditions.filter(x => x.met).length : null;
    const v = D.versions.latest && D.versions.versions[D.versions.latest], df = v && ok(v.difficulty);
    const rc = df ? countBy(df.items, 'readiness') : null;
    const mot = el('div', {class: 'card motiv'}, el('h4', {}, P.competency + ' Competency를 취득하면'),
      el('ul', {},
        el('li', {}, 'Competency ', el('b', {}, us.competencies + ' → ' + P.competencies + '개'), ', Competency 순위 ',
          el('b', {}, M.competencies.rank + '위 → ' + P.competency_rank + '위' + (P.competency_tied ? '(공동)' : ''))),
        P.next_tier ? el('li', {}, P.next_tier.tier + ' 조건 ', el('b', {}, nt.conditions.filter(x => x.met).length + '/' + nt.conditions.length + ' → ' + pm + '/' + P.next_tier.conditions.length + ' 충족')) : '',
        P.tier_up ? el('li', {}, '남은 조건: ', el('b', {}, P.tier_up.remaining.map(x => x.label + ' ' + x.gap + x.unit).join(', ')),
          ' → 채우면 ', el('b', {}, P.tier_up.tier + ' 등급 진입'), P.tier_up.same_tier.length ? ' (' + P.tier_up.same_tier.join('·') + '와 같은 등급)' : '') : ''),
      rc ? el('p', {class: 'muted', style: 'margin:4px 0 8px'}, 'M&M 준비 현황: 준비완료 ' + Math.round((rc['준비완료'] || 0) / df.items.length * 100) + '% · 미준비 ' + (rc['미준비'] || 0) + '개 · 난이도 상 ' + df.counts.high + '개') : '');
    const b1 = el('button', {class: 'btn', type: 'button'}, 'M&M 준비 현황 보기'); b1.addEventListener('click', () => goSheet('comp', 'summary'));
    const b2 = el('button', {class: 'btn', type: 'button'}, '자격 취득 현황 보기'); b2.addEventListener('click', () => goSheet('cert', 'summary2'));
    mot.append(el('div', {class: 'row', style: 'margin:0'}, b1, b2));
    row2.append(mot);
  }
  box.append(row2);

  // 4) 지표별 순위 (우리 회사만 강조색, 나머지 회색)
  const charts = el('div', {class: 'grid3', style: 'margin-top:16px'});
  for (const m of B.metrics) {
    const max = Math.max(...m.companies.map(x => x.value)) || 1;
    const bars = el('div', {class: 'rank', role: 'img', 'aria-label': m.label + ' 순위: ' + m.companies.map(x => x.company + ' ' + x.value).join(', ')});
    for (const x of m.companies) {
      bars.append(el('span', {class: x.is_us ? 'me-t' : ''}, x.company),
        hover(el('div', {class: 'track'}, el('div', {class: x.is_us ? 'us' : 'other', style: 'width:' + Math.max(1, Math.round(100 * x.value / max)) + '%'})),
          x.value + m.unit + ' · ' + x.company),
        el('span', {class: x.is_us ? 'me-t' : 'muted'}, x.value + m.unit));
    }
    charts.append(el('div', {class: 'card'}, el('h4', {}, m.label + ' · 우리 ' + m.rank + '위'), bars,
      el('p', {class: 'rule', style: 'margin:8px 0 0'}, '1위와 ' + m.gap_to_leader + m.unit + ' 차이' + (m.gap_to_next ? ' · 바로 위와 ' + m.gap_to_next + m.unit + ' 차이' : ' · 공동 또는 1위'))));
  }
  box.append(charts);

  // 5) 전체 비교 표
  box.append(el('h3', {}, '전체 비교 (가상 수치)'), table(['종합 순위', '회사', 'AWS 등급', 'Competency', 'AWS 자격 인원', '고객 사례'],
    B.table.map(r => [String(r.rank), r.is_us ? el('b', {}, r.company) : r.company, r.tier, String(r.competencies), String(r.certified_people), String(r.launches)])),
    el('p', {class: 'rule', style: 'margin-top:8px'}, '비교 회사는 익명(A사~E사)이며 수치·등급 기준은 시연용 가상 데이터입니다(data/sample/partner_benchmark.csv, tier_criteria.csv). 실제 공개 자료로 바꿀 때는 CSV만 고칩니다.'));
}

// ── 시트 전환 (엑셀 시트처럼). 고른 시트는 주소 #view=comp·cert·eval에 남겨 새로고침·공유해도 유지한다 ──
const SHEETS = ['home', 'comp', 'cert', 'eval'];
function showSheet(key, keepHash) {
  if (!SHEETS.includes(key)) key = 'home';
  for (const k of SHEETS) {
    const panel = document.getElementById('sheet-' + k), tab = document.getElementById('tab-' + k);
    if (panel) { if (k === key) panel.removeAttribute('hidden'); else panel.setAttribute('hidden', ''); }
    if (tab) { tab.className = 'sheet-tab' + (k === key ? ' on' : ''); tab.setAttribute('aria-selected', String(k === key)); }
  }
  // 주소는 #view=… 형식: #cert처럼 쓰면 브라우저가 같은 id의 칸으로 스크롤해 요약이 가려진다
  if (!keepHash) { try { history.replaceState(null, '', '#view=' + key); } catch (e) { /* file:// 등에서 막히면 무시 */ } }
  if (window.scrollTo) window.scrollTo(0, 0);
}
for (const k of SHEETS) { const t = document.getElementById('tab-' + k); if (t) t.addEventListener('click', () => showSheet(k)); }
function goSheet(key, targetId) { showSheet(key); const t = document.getElementById(targetId);
  if (t && t.scrollIntoView) t.scrollIntoView({behavior: 'smooth'}); }

const pb = document.getElementById('printbtn'); if (pb) pb.addEventListener('click', () => window.print());
renderVersions(); renderSummary(); renderCerts(); renderEval(); renderTodo(); renderHome();
showSheet(((typeof location !== 'undefined' && location.hash) || '').replace(/^#(view=)?/, ''), true);
</script></body></html>
""")


def render(data: dict, generated: str) -> str:
    # </script> 같은 문자열이 데이터에 있어도 스크립트 태그가 끊기지 않게 '</'를 이스케이프한다
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.substitute(data=payload, generated=generated)


def build(out_path=OUT_PATH) -> str:
    import time
    html = render(build_data(), time.strftime("%Y-%m-%d %H:%M"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("->", build())
