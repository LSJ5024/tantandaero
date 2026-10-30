"""신규 직렬(T6~T12) 직무 키워드 → 과목/공고 LLM 매핑 (검수용 초안 생성)
사용:
  python pipeline/map_llm.py courses <db> <out.jsonl>     과목 매핑 (신규 키워드만 대상)
  python pipeline/map_llm.py postings <db> <postings.json> <out.jsonl>   공고 매핑 (전체 키워드 대상)
- LLM_API_KEY 등은 환경변수로만 전달 (파일에 저장하지 않음)
- 결과는 jsonl 캐시에 누적 → 중단돼도 이어서 실행
- 출력 키워드 ID는 허용 목록으로 검증, 형식이 틀린 줄은 버림
"""
import json, os, re, sqlite3, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402

NEW_TRACKS = [f'T{i}' for i in range(6, 13)]
# 학과 → 주요 진출 직렬 (LLM 판단 보조용 힌트)
DEPT_HINT = [
    (r'화학공학|공업화학|화학과|신소재|이차전지|에너지저장|순환경제|환경생명화학|방사광', '이차전지·에너지·화학'),
    (r'전기공학', '이차전지·에너지·화학, 기계·자동차·로봇'),
    (r'제약|약학|생화학|미생물|식품|바이오|화장품|천연물|생물|축산|특용식물|원예|식물|수의생명', '바이오·제약·식품'),
    (r'기계|지능로봇|미래자동차|바이오시스템공학', '기계·자동차·로봇'),
    (r'건축|토목|도시공학|지역건설|안전공학|환경공학|산림|목재|지구환경|조경|농촌관광', '건설·환경·안전'),
    (r'행정|교육|아동복지|사회학|심리|정치외교|노인복지|사회적기업|철학|윤리|위기관리|의료윤리', '공공·행정·교육·복지'),
    (r'디자인|미술|조형|언론|번역|통역|과학커뮤니케이션|언어문화|영어영문|국어국문|중어중문|의류|주거환경|고고미술|사학|K컬처|문화', '디자인·미디어·콘텐츠'),
    (r'경제|경영|정보통계|수학과|소비자|빅데이터', '금융·보험'),
]


def hint(dept):
    h = [t for pat, t in DEPT_HINT if re.search(pat, dept or '')]
    return ', '.join(dict.fromkeys(', '.join(h).split(', '))) if h else '없음'


SKIP_DEPT = ('의학과', '의예과', '간호학과', '수의학과', '수의예과')   # 면허 직역 학과는 대상 외

C_PROMPT = """너는 한국 대학 교육과정과 기업 채용 직무를 모두 아는 전문가다.
각 과목을 수강하면 아래 '직무 키워드' 중 어떤 직무의 역량에 직접 도움이 되는지 판단해라.
규칙:
- 과목명과 개설학과만 보고 일반적인 수업 내용을 기준으로 판단한다.
- 직접 관련된 직무를 고른다. 막연한 연관(예: 교양 글쓰기 → 모든 직무)은 고르지 않는다.
- 전공의 기초·이론 과목(예: 미시경제원론, 재무행정론, 건축구조역학, 유기화학)도 그 전공이 일반적으로 진출하는 직무의 기초 역량이면 M 또는 L로 매핑한다.
- 학과와 무관하게 누구나 듣는 기초 수학·물리·화학·교양 과목은 '-'.
- 괄호 안 '진출'은 그 학과의 주요 진출 직렬(참고용)이다. 전공 과목은 가급적 그 직렬 안에서 가장 가까운 직무로 매핑하고,
  과목 내용이 다른 직렬에 더 맞으면 그쪽을 고른다. '-'는 어떤 직무와도 직접 관련이 없을 때만 쓴다.
- 주 키워드 1개, 부 키워드 0~2개. 관련 직무가 없으면 '-'.
- 확신도: H(과목명이 직무와 거의 일치), M(핵심 역량에 도움), L(간접적).
- 반드시 아래 목록의 ID만 쓴다.
출력 형식(설명 없이 과목마다 한 줄):
과목ID|주ID|부ID1,부ID2|H
과목ID|-
직무 키워드:
{kws}"""

P_PROMPT = """너는 채용공고를 직무로 분류하는 전문가다.
각 공고의 제목·모집직종·직무 키워드를 보고, 아래 '직무 키워드' 중 이 공고가 뽑는 직무를 골라라.
규칙:
- 주 키워드 1개(가장 핵심 직무), 부 키워드 0~2개.
- X(제외)는 대졸자가 지원할 직무가 아닌 경우에만 쓴다: 단순 생산직·오퍼레이터·조작원, 운전·지게차, 판매·서빙,
  간병·요양·청소·경비, 단기 아르바이트, 직무가 불분명한 채용박람회 안내.
- 설계, 생산관리·공정관리, 생산기술, 설비보전·공무, 품질관리, 연구·분석, 기술영업, 관리직·사무직은 X가 아니다
  (예: '기계설계직원 모집', '화학제품 생산관리직', '자동차 부품 생산기술/설비보전', '태양광 설계', 'ESS사업 신입'은 포함).
- 목록에 맞는 직무가 없으면 '-'.
- 반드시 아래 목록의 ID만 쓴다.
출력 형식(설명 없이 공고마다 한 줄):
공고ID|주ID|부ID1,부ID2
공고ID|X
직무 키워드:
{kws}"""


def kw_text(kws):
    return '\n'.join(f"{k}: {v['직렬']} > {v['키워드']} ({v['설명']})" for k, v in kws.items())


def ask(system, lines, cfg):
    msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': '\n'.join(lines)}]
    for i in range(15):
        try:
            return llm.call(msgs, cfg, timeout=90, max_tokens=2500, json_mode=False)
        except Exception as e:  # 분당 토큰 제한 등 → 대기 후 재시도
            print('  retry', i, str(e)[:120], flush=True)
            time.sleep(min(25 + 10 * i, 90))
    raise RuntimeError('LLM 호출 실패')


def parse(text, ids, allowed, x_ok):
    out = {}
    for ln in text.splitlines():
        p = [x.strip() for x in ln.strip().strip('`').split('|')]
        if not p or p[0] not in ids:
            continue
        if len(p) >= 2 and p[1] in ('-', 'X'):
            out[p[0]] = {'main': None, 'sub': [], 'conf': None, 'x': p[1] == 'X' and x_ok}
            continue
        if len(p) >= 2 and p[1] in allowed:
            sub = [s.strip() for s in (p[2].split(',') if len(p) > 2 else []) if s.strip() in allowed and s.strip() != p[1]][:2]
            conf = p[3] if len(p) > 3 and p[3] in ('H', 'M', 'L') else 'M'
            out[p[0]] = {'main': p[1], 'sub': sub, 'conf': conf, 'x': False}
    return out


def run(items, system, allowed, cache, batch, x_ok=False):
    done = {}
    if os.path.exists(cache):
        for ln in open(cache, encoding='utf-8'):
            r = json.loads(ln); done[r['id']] = r
    todo = [(i, t) for i, t in items if i not in done]
    print('total', len(items), 'todo', len(todo), flush=True)
    cfg = llm.config()
    with open(cache, 'a', encoding='utf-8') as f:
        for b in range(0, len(todo), batch):
            chunk = todo[b:b + batch]
            ids = {i for i, _ in chunk}
            res = parse(ask(system, [t for _, t in chunk], cfg), ids, allowed, x_ok)
            miss = ids - set(res)
            if miss:   # 누락분 1회 재요청
                res.update(parse(ask(system, [t for i, t in chunk if i in miss], cfg), miss, allowed, x_ok))
            for i in ids:
                if i in res:
                    f.write(json.dumps({'id': i, **res[i]}, ensure_ascii=False) + '\n')
            f.flush()
            print(f'{b + len(chunk)}/{len(todo)} ok {len(res)}', flush=True)
            time.sleep(4)


def main():
    mode, db = sys.argv[1], sys.argv[2]
    con = sqlite3.connect(db); con.row_factory = sqlite3.Row
    kw = {r['kw_id']: dict(r) for r in con.execute('select * from job_keyword')}
    tr = {r['직렬']: r['track_id'] for r in con.execute('select * from job_track')}
    if mode == 'courses':
        new = {k: v for k, v in kw.items() if tr[v['직렬']] in NEW_TRACKS}
        items = []
        for r in con.execute('select course_id, 과목명, 학과 from course where 선택가능=1 order by 학과, 과목명'):
            dept = (r['학과'] or '').split(',')[0].split('/')[0].strip()
            if any(d in (r['학과'] or '') for d in SKIP_DEPT) and not any(
                    x in (r['학과'] or '') for x in ('제약', '약학', '바이오')):
                continue
            items.append((r['course_id'], f"{r['course_id']}: {r['과목명']} ({dept} / 진출: {hint(r['학과'])})"))
        run(items, C_PROMPT.format(kws=kw_text(new)), set(new), sys.argv[3], batch=70)
    else:
        P = json.load(open(sys.argv[3], encoding='utf-8'))
        groups = {}
        for p in P:                                   # 수집 검색어의 직렬별로 묶어, 그 직렬 키워드만 제시 (토큰 절약)
            d = p.get('detail', {})
            t = f"{p['id']}: {p['title']} / 모집직종: {d.get('모집 직종') or '-'} / 키워드: {(d.get('직종 키워드') or '-')[:60]}"
            groups.setdefault(p['track_query'].split(' ')[0], []).append((p['id'], t))
        for tid, items in groups.items():
            if tid in NEW_TRACKS:                     # 신규 수집 공고: 해당 직렬 키워드 + 제외(X) 판단
                sub, x_ok = {k: v for k, v in kw.items() if tr[v['직렬']] == tid}, True
            else:                                     # 기존 공고: 신규 직렬 키워드만 추가 후보로
                sub, x_ok = {k: v for k, v in kw.items() if tr[v['직렬']] in NEW_TRACKS}, False
            print('group', tid, len(items), flush=True)
            run(items, P_PROMPT.format(kws=kw_text(sub)), set(sub), sys.argv[4], batch=25, x_ok=x_ok)

if __name__ == '__main__':
    main()
