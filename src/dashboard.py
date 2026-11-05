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
                 "note": r.get("internal_note") or ""} for r in data["requirements"]]
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
                       "readiness": LABEL_KO[i["readiness"]], "reasons": i["reasons"]} for i in items]}


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

    items = [{"id": i["id"], "title": i["title"], "cases": cases(i["customer_examples_required"]),
              "deliverables": [d["name"] for d in i["deliverables"]]} for i in r["items"]]
    return {"total": sum(len(i["deliverables"]) for i in items),
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


def build_data() -> dict:
    return {"versions": version_data(), "certs": certification_data(), "eval": evaluation_data(),
            "not_implemented": []}


# ── HTML ──────────────────────────────────────────────────────────────────

PAGE = Template(r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CompassPilot 대시보드</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2330;--muted:#5d6675;--line:#e2e5ea;--accent:#2f6fde;--ok:#1f8a4c;--bad:#c7392f;--warn:#b7791f;--chip:#eef2fb}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--card:#1d2128;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2e333c;--accent:#6b9cff;--ok:#4cc17d;--bad:#ff7b70;--warn:#e0b050;--chip:#26304a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,-apple-system,"Malgun Gothic",sans-serif}
header{padding:20px 16px 8px;max-width:1200px;margin:auto}h1{font-size:20px;margin:0}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1200px;margin:auto;padding:8px 16px 40px;display:grid;gap:16px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
h2{font-size:16px;margin:0 0 12px}h3{font-size:14px;margin:16px 0 8px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px}.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}
.chip{display:inline-block;background:var(--chip);border-radius:10px;padding:0 8px;font-size:12px;white-space:nowrap}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}.muted{color:var(--muted)}
.note{color:var(--warn);font-size:12px;white-space:pre-line}.chg{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-line}
select{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg)}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.bar{height:8px;background:var(--accent);border-radius:4px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:16px 0 12px;flex-wrap:wrap}
.tab{font:inherit;background:none;border:0;border-bottom:2px solid transparent;padding:6px 10px;color:var(--muted);cursor:pointer}
.tab.on{color:var(--fg);border-bottom-color:var(--accent);font-weight:600}
input[type=search]{font:inherit;padding:4px 8px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--fg);min-width:180px}
details.sec{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;overflow-x:auto}
details.sec>summary{cursor:pointer;font-weight:600;font-size:16px}
details.sec[open]>summary{margin-bottom:12px}
.rule{font-size:12px;color:var(--muted);margin:0 0 8px}
footer{max-width:1200px;margin:auto;padding:0 16px 24px;color:var(--muted);font-size:12px}
</style></head><body>
<header><h1>CompassPilot · CSP 파트너 등급 관리 대시보드</h1>
<p>Competency(AWS M&amp;M Assessment)와 임직원 자격, 파트너 등급의 두 축을 한 화면에서 봅니다. 생성: $generated</p></header>
<main>
<section id="ver"></section>
<section id="cert"></section>
<section id="todo"></section>
<details class="sec"><summary id="evalsum">③ 자체 평가 결과</summary><div id="eval"></div></details>
</main>
<footer>사내 확인용. 자격 현황은 숫자 집계만 표시합니다(이름 없음). 원문·ID는 AWS 영문 그대로입니다.</footer>
<script id="data" type="application/json">$data</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const el = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else e.setAttribute(k, v); }
  for (const k of kids) e.append(k instanceof Node ? k : document.createTextNode(k ?? '')); return e; };
const kpi = (v, label) => el('div', {class: 'kpi'}, el('b', {}, String(v)), el('span', {}, label));
const table = (heads, rows) => el('table', {}, el('thead', {}, el('tr', {}, ...heads.map(h => el('th', {}, h)))),
  el('tbody', {}, ...rows.map(r => el('tr', {}, ...r.map(c => el('td', {}, c))))));
const TYPE = {substantive: '실질 변경', minor_notation: '경미(표기)', minor_typo: '경미(오타)', added: '추가'};
const fmt = v => v == null ? '-' : (typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v));
const changesText = cs => (cs || []).map(c => `"$${c.old}" → "$${c.new}"`).join('\n');

function renderVersions() {
  const box = document.getElementById('ver'); box.replaceChildren(el('h2', {}, '① Competency · Assessment 버전'));
  const V = D.versions; if (!V.latest) { box.append(el('p', {class: 'muted'}, '데이터 없음')); return; }
  const sel = el('select', {id: 'vsel'}, ...V.labels.slice().reverse().map(l => el('option', {value: l}, `$${l} 판`)));
  box.append(el('div', {class: 'row'}, el('label', {for: 'vsel'}, '버전 선택'), sel,
    el('span', {class: 'muted'}, `등록 버전 $${V.labels.length}개 · 새 버전은 data/private/versions/에 넣고 색인 명령 실행`)));
  const body = el('div'); box.append(body);
  const draw = label => {
    const v = V.versions[label], d = v.diff; body.replaceChildren();
    const df = v.difficulty && !v.difficulty.error ? v.difficulty : null;
    const dv = v.deliverables && !v.deliverables.error ? v.deliverables : null;
    body.append(el('p', {class: 'muted'}, `유효기간: $${v.validity || '-'}`));
    const k = el('div', {class: 'kpis'}, kpi(v.total, '요구사항'));
    if (d) { k.append(kpi(d.counts.added, '추가'), kpi(d.counts.removed, '삭제'), kpi(d.counts.substantive, '실질 변경'),
      kpi(d.counts.minor, '경미 변경'), kpi(d.counts.sheet_notes_changed, '안내문 변경')); }
    if (df) k.append(kpi(df.counts.high, '난이도 상'), kpi(df.counts.medium, '난이도 중'), kpi(df.counts.low, '난이도 하'));
    if (dv) k.append(kpi(dv.total, '산출물'));
    body.append(k);
    const nChanges = d ? d.added.length + d.removed.length + d.changed.length + d.sheet_notes.length : 0;
    const TABS = [['changes', d ? `변경 내역 ($${nChanges})` : '변경 내역'], ['prep', '준비 현황 (난이도·산출물)'],
                  ['all', `요구사항 전체 ($${v.total})`]];
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

// 탭·필터 상태는 버전을 바꿔도 유지한다
const STATE = {tab: 'prep', q: '', level: '', scope: '', orgLevel: 'by_team'};
const LEVEL_CLASS = {'상': 'bad', '중': 'note', '하': 'ok'};
const noteSpan = n => el('span', {class: 'note'}, n ? '[내부 메모] ' + n : '');

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
  pane.append(el('div', {class: 'row'}, ...kids, count));
  return count;
}
const matchQ = (r) => { const q = STATE.q.trim().toLowerCase(); return !q || r.id.toLowerCase().includes(q) || r.title.toLowerCase().includes(q); };

function drawChanges(pane, v, label) {
  const d = v.diff;
  if (!d) { pane.append(el('p', {class: 'muted'}, '첫 등록 버전이라 비교 대상이 없습니다.')); return; }
  pane.append(el('p', {class: 'rule'}, `$${d.from} → $${label}. 실질 변경 = 의미가 바뀜, 경미(표기) = 대소문자·문장부호만, 경미(오타) = 철자만 (파이썬 규칙)`));
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

function drawPrep(pane, v, df, dv, label) {
  if (!df && !dv) { pane.append(el('p', {class: 'muted'}, '데이터 없음 (난이도·산출물)')); return; }
  pane.append(el('p', {class: 'rule'}, '난이도 점수: 미준비 +2 · 일부 +1 · 고객 사례 4건 증빙 항목 +1 · 이번 버전 신규 +1 → 0~1점 하, 2점 중, 3~4점 상. '
    + '준비 상태는 data/sample/readiness.csv(가상 데이터), 산출물은 색인할 때 원문에서 한 번 추출한 결과(근거 문장 원문 대조)입니다.'));
  if (!df) pane.append(el('p', {class: 'muted'}, '난이도 데이터 없음' + (v.difficulty && v.difficulty.error ? ' (' + v.difficulty.error + ')' : '')));
  if (!dv) pane.append(el('p', {class: 'muted'}, '산출물 데이터 없음' + (v.deliverables && v.deliverables.error ? ' (' + v.deliverables.error + ')' : '')));
  const byDiff = Object.fromEntries((df ? df.items : []).map(i => [i.id, i]));
  const byDel = Object.fromEntries((dv ? dv.items : []).map(i => [i.id, i]));
  const rowsAll = v.requirements.map(r => ({...r, d: byDiff[r.id], x: byDel[r.id]}))
    .sort((a, b) => ((b.d ? b.d.score : -1) - (a.d ? a.d.score : -1)) || a.id.localeCompare(b.id));
  const count = filterBar(pane, {level: !!df}, () => redraw());
  const holder = el('div'); pane.append(holder);
  const redraw = () => {
    const rows = rowsAll.filter(r => matchQ(r) && (!STATE.scope || r.scope === STATE.scope)
      && (!STATE.level || (r.d && r.d.level === STATE.level)));
    count.textContent = `$${rows.length}개 표시 / 전체 $${rowsAll.length}개`;
    holder.replaceChildren(table(['난이도', '점수', 'ID', '제목', '준비 상태', '준비 범위', '산출물 체크리스트', '점수 근거'], rows.map(r => [
      r.d ? el('span', {class: LEVEL_CLASS[r.d.level] || ''}, r.d.level) : '-', r.d ? String(r.d.score) : '-', r.id, r.title,
      r.d ? r.d.readiness : '-', r.x ? r.x.cases : '-',
      el('span', {class: 'chg'}, r.x ? r.x.deliverables.map(n => '☐ ' + n).join('\n') : '-'),
      el('span', {class: 'chg'}, r.d ? r.d.reasons.join('\n') : '-')])));
  };
  redraw();
}

function drawAll(pane, v) {
  const count = filterBar(pane, {level: false}, () => redraw());
  const holder = el('div'); pane.append(holder);
  const redraw = () => {
    const rows = v.requirements.filter(r => matchQ(r) && (!STATE.scope || r.scope === STATE.scope));
    count.textContent = `$${rows.length}개 표시 / 전체 $${v.requirements.length}개`;
    holder.replaceChildren(table(['ID', '제목', '시트', '영역', '범위', '내부 메모'],
      rows.map(r => [r.id, r.title, r.sheet, r.area, r.scope, el('span', {class: 'note'}, r.note)])));
  };
  redraw();
}

function renderCerts() {
  const box = document.getElementById('cert'); box.replaceChildren(el('h2', {}, '② 임직원 자격 현황 (숫자만, 가상 데이터)'));
  const C = D.certs; if (!C) { box.append(el('p', {class: 'muted'}, '데이터 없음')); return; }
  const T = C.targets && !C.targets.error ? C.targets : null;
  if (T) drawTargets(box, T);
  else box.append(el('p', {class: 'muted'}, '대상 데이터 없음' + (C.targets && C.targets.error ? ' (' + C.targets.error + ')' : '')));

  box.append(el('h3', {}, '보유 자격 (대상 여부와 무관한 전체 보유)'));
  box.append(el('div', {class: 'kpis'}, kpi(C.total, '자격 건수'), kpi(C.employees, '보유 인원'),
    ...Object.entries(C.by_vendor).map(([v, n]) => kpi(n, v))));
  const max = Math.max(...C.by_cert.map(x => x[1]));
  box.append(el('h3', {}, '자격증별 건수'), table(['자격증', '건수', ''], C.by_cert.map(([c, n]) =>
    [c, String(n), el('div', {class: 'bar', style: `width:$${Math.round(120 * n / max)}px`})])));
  box.append(el('h3', {}, '사업부 × 벤더 (보유 건수)'), table(['사업부', ...C.vendors], C.divisions.map((d, i) => [d, ...C.matrix[i].map(String)])));
  box.append(el('p', {class: 'muted'}, '명단(이름)은 CLI에서 권한별로만 조회됩니다: 인사팀 전사 · 담당 사업부 · 팀장 팀 · 그룹장 그룹.'));
}

const pct = r => r == null ? '-' : (r * 100).toFixed(1) + '%';
const rateBar = r => el('div', {class: 'bar', style: `width:$${Math.round(120 * (r || 0))}px`});

function drawTargets(box, T) {
  const P = T.by_person;
  box.append(el('p', {class: 'rule'}, '취득 대상(data/sample/cert_targets.csv) 대비 실적입니다. 대상 벤더의 자격을 1건 이상 보유하면 취득으로 봅니다. 벤더별은 연인원, 사람별은 실인원 기준입니다.'));
  box.append(el('div', {class: 'kpis'}, kpi(T.total.target, '대상 (연인원)'), kpi(T.total.achieved, '취득'),
    kpi(T.total.not_achieved, '미취득'), kpi(pct(T.total.rate), '취득률'), kpi(P.people, '대상 인원 (실인원)'),
    kpi(P.all, '전부 취득'), kpi(P.partial, '일부 취득'), kpi(P.none, '미취득 (0건)')));

  box.append(el('h3', {}, '1. 벤더별 취득 현황 (연인원)'), table(['벤더', '대상', '취득', '미취득', '취득률', ''], [
    ...T.vendors.map(v => { const x = T.by_vendor[v]; return [v, String(x.target), String(x.achieved), String(x.not_achieved), pct(x.rate), rateBar(x.rate)]; }),
    [el('b', {}, '합계'), String(T.total.target), String(T.total.achieved), String(T.total.not_achieved), pct(T.total.rate), rateBar(T.total.rate)]]));

  const ratio = n => pct(P.people ? n / P.people : null);
  box.append(el('h3', {}, '2. 사람별 취득 현황 (실인원)'), table(['구분', '인원', '비율'], [
    ['취득 대상 인원', String(P.people), ratio(P.people)], ['전부 취득 (대상 벤더 모두)', String(P.all), ratio(P.all)],
    ['일부 취득', String(P.partial), ratio(P.partial)], ['미취득 (0건)', String(P.none), ratio(P.none)],
    ['(참고) 2개 이상 벤더 대상자', String(P.multi_vendor), ratio(P.multi_vendor)]]));

  const LEVELS = [['by_division', '사업부'], ['by_team', '팀'], ['by_group', '그룹']];
  const lv = el('select', {'aria-label': '조직 단위'}, ...LEVELS.map(([k, n]) => el('option', {value: k}, n + '별')));
  lv.value = STATE.orgLevel;
  const holder = el('div');
  const drawOrg = () => {
    const depth = LEVELS.findIndex(([k]) => k === lv.value) + 1;
    const heads = ['사업부', '팀', '그룹'].slice(0, depth);
    holder.replaceChildren(table([...heads, '대상 인원', ...T.vendors.map(v => v + ' 대상/취득'), '취득률'],
      T[lv.value].map(r => [...r.org, String(r.people), ...T.vendors.map(v => r.vendors[v].target ? `$${r.vendors[v].target} / $${r.vendors[v].achieved}` : '-'), pct(r.rate)])));
  };
  lv.addEventListener('change', () => { STATE.orgLevel = lv.value; drawOrg(); });
  box.append(el('h3', {}, '3. 조직별 취득 현황'), el('div', {class: 'row'}, el('label', {}, '조직 단위'), lv), holder);
  drawOrg();

  const K = T.checks;
  const bad = n => el('span', {class: n ? 'bad' : 'ok'}, String(n));
  box.append(el('h3', {}, '점검'), table(['항목', '건수', '설명'], [
    ['조직도에 없는 사번', bad(K.unknown_employee_ids), '0이어야 정상. 집계에서 제외했습니다'],
    ['중복 입력 행', bad(K.duplicate_rows), '0이어야 정상. 한 번만 집계했습니다'],
    ['대상이 아닌데 보유', String(K.holders_not_target), '참고. 대상 목록 누락인지 확인하세요']]));
}

function renderEval() {
  const box = document.getElementById('eval'); box.replaceChildren();
  const E = D.eval; if (!E) { box.append(el('p', {class: 'muted'}, '데이터 없음 (python -m evaluation.run_eval --round N)')); return; }
  const s = E.summary;
  document.getElementById('evalsum').textContent =
    `③ 자체 평가 결과 · 라운드 $${E.round} · $${s.passed}/$${s.total} 통과 · judge $${fmt(s.judge_mean_score)} (눌러서 펼치기)`;
  box.append(el('p', {class: 'muted'}, `최신 라운드 $${E.round} · $${E.run_at || ''} · $${(E.model || {}).chat || ''}`));
  box.append(el('div', {class: 'kpis'}, kpi(`$${s.passed}/$${s.total}`, '규칙 판정 통과'), kpi(fmt(s.judge_mean_score), 'LLM judge 평균(1~5)'),
    ...Object.entries(s.ragas_mean || {}).map(([m, v]) => kpi(fmt(v), m))));
  box.append(el('h3', {}, '성공 기준'), table(['기준', '값', '판정'], Object.entries(s.criteria).map(([k, v]) =>
    [k, v.value, el('span', {class: v.met ? 'ok' : 'bad'}, v.met ? '충족' : '미달')])));
  box.append(el('h3', {}, '라운드별 추이'), table(['라운드', '통과', 'judge', 'faithfulness'],
    E.history.map(h => [String(h.round), `$${h.passed}/$${h.total}`, fmt(h.judge), fmt(h.faithfulness)])));
  box.append(el('h3', {}, '문항별 결과'), table(['#', '유형', '사용자', '질문', '결과', '판정', 'judge', 'faith'],
    E.items.map(i => [String(i.id), i.type, i.user, i.question, el('span', {class: i.passed ? 'ok' : 'bad'}, i.passed ? '통과' : '실패'),
      i.detail, fmt(i.judge), fmt(i.faith)])));
}

function renderTodo() {
  const box = document.getElementById('todo');
  if (!D.not_implemented.length) { box.remove ? box.remove() : box.replaceChildren(); return; }
  box.replaceChildren(el('h2', {}, '④ 준비 중'));
  box.append(el('p', {class: 'muted'}, '미구현: ' + D.not_implemented.join(', ')));
}
renderVersions(); renderCerts(); renderEval(); renderTodo();
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
