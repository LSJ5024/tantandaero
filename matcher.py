"""매칭 엔진: 대표 과목(최대 10개) + 관심 직무 + 자격증 + 학력 + 지역 → 공고 적합도(0~100)

점수 구성 (설명 가능한 규칙 기반, LLM 미사용)
  직무 적합  55  공고 직무 키워드를 내 과목·관심 키워드가 얼마나 덮는가
  직렬 일치  10  공고의 주 키워드가 내가 고른 직렬(최대 2개)에 속하는가
  자격증     15  공고에 적힌 자격증 보유 15 / 공고 직무의 대표 자격증 보유 8
  학력       10  지원 가능하면 10 (미달이면 지원 불가로 분리)
  지역       10  희망 지역(시도) 일치 또는 희망 지역 미지정
지원 불가: 학력 미달, 필수 자격증(운전면허 제외) 미보유, 마감 지남
"""
import re
import sqlite3
from datetime import date

EDU_LEVELS = [('박사', 7), ('석사', 6), ('대졸(4년)', 5), ('대학졸업(4년)', 5), ('대졸(2~3년)', 4), ('대졸(2∼3년)', 4),
              ('고졸', 3), ('중졸', 1), ('무관', 0)]
EDU_NAME = {0: '학력무관', 3: '고졸', 4: '전문대졸', 5: '대졸(4년)', 6: '석사', 7: '박사'}
W = {'fit': 55, 'track': 10, 'cert': 15, 'edu': 10, 'region': 10}


def norm(s):
    return re.sub(r'[\s·()\-]', '', str(s or '')).lower()


def min_edu(text):
    """'대졸(2~3년)~석사' 같은 범위 표기에서 최소 학력 요구를 뽑는다."""
    t = text or ''
    found = [v for k, v in EDU_LEVELS if k in t]
    return min(found) if found else 0


def required_certs(text):
    """'우대 전산세무1급 필수 전산세무2급' → ['전산세무2급'] (운전면허는 별도 표시용으로 분리)"""
    req, mode = [], None
    for tok in (text or '').split():
        if tok in ('필수', '우대', '기타', '관계없음'):
            mode = tok
            continue
        if mode == '필수':
            req.append(tok)
    lic = [r for r in req if '운전' in r or '면허' in r]
    return [r for r in req if r not in lic], lic


class Matcher:
    def __init__(self, db_path):
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        self.kw = {r['kw_id']: dict(r) for r in con.execute('select * from job_keyword')}
        self.tracks = [dict(r) for r in con.execute('select * from job_track')]
        self.courses = {r['course_id']: dict(r) for r in con.execute(
            "select course_id, 과목명, 학과, 직무키워드, 선택가능, 매핑상태 from course")}
        self.ck = {}
        for r in con.execute('select * from course_keyword'):
            self.ck.setdefault(r['course_id'], []).append((r['kw_id'], r['구분']))
        self.posts = {r['posting_id']: dict(r) for r in con.execute(
            "select * from job_posting where 포함여부='포함'")}
        self.pk = {}
        for r in con.execute('select * from posting_keyword'):
            self.pk.setdefault(r['posting_id'], []).append((r['kw_id'], r['구분']))
        for p in self.posts.values():
            p['edu_min'] = min_edu(p.get('학력'))
            p['req_certs'], p['req_license'] = required_certs(p.get('자격면허'))
        con.close()

    # ---------- 보조 ----------
    def track_of(self, kw_id):
        return 'T' + kw_id[1:-2]          # J101 → T1, J1104 → T11 (뒤 두 자리는 직렬 내 순번)

    def search_courses(self, q, limit=20):
        qn = norm(q)
        if not qn:
            return []
        out = []
        for c in self.courses.values():
            if not c['선택가능']:
                continue
            if qn in norm(c['과목명']):
                out.append(c)
        out.sort(key=lambda c: (not norm(c['과목명']).startswith(qn), c['매핑상태'] != '매핑', len(c['과목명'])))
        return [{'course_id': c['course_id'], '과목명': c['과목명'], '학과': (c['학과'] or '')[:40],
                 '직무키워드': c['직무키워드'] or ''} for c in out[:limit]]

    def cert_options(self):
        s = set()
        for k in self.kw.values():
            for c in str(k['대표_자격증'] or '').split(','):
                c = c.strip()
                if c and c != '-':
                    s.add(c)
        s |= {'전산회계1급', '전산회계2급', '전산세무1급', '전산세무2급', 'TOEIC', 'OPIc', '컴퓨터활용능력1급',
              '컴퓨터활용능력2급', 'ADsP', 'SQLD', '정보처리기사', '물류관리사', '품질경영기사', '화공기사',
              '전기기사', '전자기사', '반도체설비보전기능사', '위험물산업기사', '자동차운전면허'}
        return sorted(s)

    # ---------- 핵심 ----------
    def strengths(self, profile):
        """내 키워드 강도: 과목 주 키워드 2, 부 키워드 1, 관심 키워드 2"""
        S, src = {}, {}
        for cid in profile.get('courses', [])[:10]:
            for k, g in self.ck.get(cid, []):
                S[k] = S.get(k, 0) + (2 if g == '주' else 1)
                src.setdefault(k, []).append(self.courses[cid]['과목명'])
        for k in profile.get('interests', []):
            S[k] = S.get(k, 0) + 2
        return S, src

    def score_one(self, p, profile, S, src):
        kws = self.pk.get(p['posting_id'], [])
        if not kws:
            return None
        tot = sum(2 if g == '주' else 1 for _, g in kws)
        cov = sum((2 if g == '주' else 1) * min(1, S.get(k, 0) / 4) for k, g in kws)   # 강도 4(과목 2개 또는 과목+관심)면 충족
        fit = W['fit'] * cov / tot

        main = [k for k, g in kws if g == '주'][0]
        tracks = profile.get('tracks', [])
        track = W['track'] if (not tracks or self.track_of(main) in tracks) else 0

        mycerts = [norm(c) for c in profile.get('certs', [])]
        ptext = norm(' '.join(str(p.get(x) or '') for x in ('자격면허', '우대조건', '기타우대', '직무내용')))
        rep = norm(' '.join(str(self.kw[k]['대표_자격증']) for k, _ in kws))
        cert_hit = [c for c in profile.get('certs', []) if norm(c) and norm(c) in ptext]
        cert_rep = [c for c in profile.get('certs', []) if norm(c) and norm(c) in rep]
        cert = W['cert'] if cert_hit else (8 if cert_rep else 0)

        reasons_no = []
        if p['edu_min'] > profile.get('edu', 5):
            reasons_no.append(f"학력 요건 {EDU_NAME.get(p['edu_min'], p['edu_min'])} 이상")
        miss = [r for r in p['req_certs'] if not any(m and (m in norm(r) or norm(r) in m) for m in mycerts)]
        if miss:
            reasons_no.append('필수 자격 ' + ', '.join(miss))
        if p.get('마감일') and p['마감일'] < profile.get('today', date.today().isoformat()):
            reasons_no.append('마감 지남')
        edu = W['edu']

        regions = profile.get('regions', [])
        region = W['region'] if (not regions or p.get('시도') in regions) else 0

        score = round(fit + track + cert + edu + region)
        match = [{'kw': f"{k} {self.kw[k]['키워드']}", '과목': sorted(set(src.get(k, [])))[:3],
                  '관심': k in profile.get('interests', [])} for k, g in kws if S.get(k)]
        gap = [f"{k} {self.kw[k]['키워드']}" for k, g in kws if not S.get(k)]
        dday = None
        if p.get('마감일'):
            dday = (date.fromisoformat(p['마감일']) - date.fromisoformat(profile.get('today', date.today().isoformat()))).days
        return {
            'posting_id': p['posting_id'], 'company': p['company'], 'title': p['title'], 'url': p['url'],
            'score': score, 'parts': {'직무': round(fit), '직렬': track, '자격': cert, '학력': edu, '지역': region},
            'eligible': not reasons_no, 'reasons_no': reasons_no,
            'match': match, 'gap': gap, 'cert_hit': cert_hit, 'license': p['req_license'],
            '시도': p.get('시도'), '시군구': ('' if (p.get('시군구') or '').strip(',') == p.get('시도') else (p.get('시군구') or '').strip(',')), '충북': bool(p.get('충북여부')),
            '연봉': p.get('연봉_만원_추정'), '임금': p.get('임금'), '학력': p.get('학력'), '경력': p.get('경력'),
            '마감일': p.get('마감일'), 'dday': dday, '기업형태': p.get('기업형태'), '기업규모': p.get('기업규모'),
            '직무키워드': p.get('직무키워드_매핑'),
        }

    def match(self, profile, sort='score', cb_first=False, include_ineligible=False, limit=50):
        S, src = self.strengths(profile)
        res = [r for r in (self.score_one(p, profile, S, src) for p in self.posts.values()) if r]
        ok = [r for r in res if r['eligible']]
        no = [r for r in res if not r['eligible']]
        key = {'score': lambda r: -r['score'],
               'deadline': lambda r: (r['dday'] is None, r['dday'] if r['dday'] is not None else 9999),
               'salary': lambda r: -(r['연봉'] or 0)}[sort]
        ok.sort(key=lambda r: (-r['score'], -len(r['match']), r['dday'] if r['dday'] is not None else 999))
        ok.sort(key=key)
        if cb_first:
            ok.sort(key=lambda r: not r['충북'])
        out = {'results': ok[:limit], 'count': len(ok), 'ineligible_count': len(no),
               'my_keywords': sorted(({'kw': f"{k} {self.kw[k]['키워드']}", 'strength': v} for k, v in S.items()),
                                     key=lambda x: -x['strength'])}
        if include_ineligible:
            out['ineligible'] = sorted(no, key=lambda r: -r['score'])[:30]
        out['cert_gap'] = self.cert_gap(profile, ok + no)
        return out

    def cert_gap(self, profile, rows):
        """상위 공고들에서 자주 요구·우대되는데 내가 없는 자격증"""
        mine = {norm(c) for c in profile.get('certs', [])}
        cnt = {}
        for r in sorted(rows, key=lambda r: -r['score'])[:40]:
            p = self.posts[r['posting_id']]
            for c in re.findall(r'(?:우대|필수)\s+([가-힣A-Za-z]+(?:\d급)?)', p.get('자격면허') or ''):
                if '운전' in c or norm(c) in mine or c in ('기타', '관계없음'):
                    continue
                cnt[c] = cnt.get(c, 0) + 1
        return sorted(({'cert': k, 'posts': v} for k, v in cnt.items()), key=lambda x: -x['posts'])[:5]
