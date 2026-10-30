"""충북대 교과목 마스터 DB 빌드
입력: 강좌목록 + 교육과정 (각 2024-1 ~ 2026-2, 6개 학기)
출력: cbnu_courses.sqlite, cbnu_courses.xlsx
"""
import re, sys, sqlite3, unicodedata
import pandas as pd

A, OUT = sys.argv[1], sys.argv[2]
# 학기 라벨은 2026 파일과의 과목코드·교수 겹침으로 추정 (파일 안에 연도·학기 정보 없음)
SEMS = {'2024-1': 'f74ef1f2-________20261028105514315963.xlsx',
        '2024-2': 'f7ee6a9f-________20261028105420582758.xlsx',
        '2025-1': 'e3c3591b-________20261028105123432292.xlsx',
        '2025-2': 'b65edf20-________20261028105244986237.xlsx',
        '2026-1': 'fef60e47-________20261028104837456251.xlsx',
        '2026-2': '16f34022-________20261027123211912238.xlsx'}
# 교육과정 파일 학기 라벨: 강좌 파일과의 과목코드 겹침으로 확인
CURS = {'2024-1': '95e2c117-________20261028111714478898.xlsx',
        '2024-2': '5b2aec9f-________20261028111345741237.xlsx',
        '2025-1': '1df2cd20-________20261028110712156412.xlsx',
        '2025-2': '1224f33e-________20261028111027312314.xlsx',
        '2026-1': '3e2d7fee-________20261028110422796776.xlsx',
        '2026-2': 'e9447309-________20261027123506409139.xlsx'}

OFF_COLS = ['순번', '학년', '이수구분', '과목코드', '과목명', '분반', '학점', '강의구분', '성적부여', '외국어',
            '담당교수', '수업시간', '계획서', '첨부', '수업방식', '이론시간', '이론시수', '실기시간', '실기시수',
            '신청인원', '수강정원', '수강인원']
EXCL_COLLEGE = ['융합전공', '소단위전공', '학생설계전공', '연계전공']
COMMON = {'5100': '전자정보대학 공통', '6208': '경영정보학과'}

TRACK_A = ['경영정보학과', '경영학부', '경영학자율전공학부', '국제경영학과', '소프트웨어학부',
           '소프트웨어학부 / 소프트웨어전공', '소프트웨어학부 / 인공지능전공', '컴퓨터공학과',
           '정보통계학과', '융합소프트웨어전공', '전자정보대학 공통']
TRACK_B = ['화학공학과', '전자공학과', '전자공학부', '전자공학부 / 반도체공학전공',
           '전자공학부 / 전자공학전공', '반도체공학부', '시스템반도체학과', '전자정보대학 공통']
GYO = ['교양선택', '일반선택', '기초공통', '교직필수', '공통과목']


def norm(s):
    s = unicodedata.normalize('NFKC', str(s)).upper()
    s = re.sub(r'\s+', '', s).replace('및', '&').replace('·', '&')
    return s


def load_off(path, sem):
    d = pd.read_excel(path, header=None, skiprows=2, dtype=str)
    d.columns = OFF_COLS
    d = d.dropna(subset=['과목코드'])
    d['학기'] = sem
    return d


off = pd.concat([load_off(A + f, k) for k, f in SEMS.items()], ignore_index=True)
for c in ['과목명', '담당교수', '분반']:
    off[c] = off[c].fillna('').str.strip()

def load_cur(path, sem):
    d = pd.read_excel(path, header=None, skiprows=2, dtype=str)
    d.columns = ['순번', '개설대학', '개설학과', '주관부서', '학년', '유형', '학기구분', '이수구분', '과목코드', '과목명', '학점', '과정']
    d['개설학과'] = d['개설학과'].fillna(d['주관부서'])   # 대학 공통 과목은 학과가 비어 있음 → 주관부서로 채움
    d = d.dropna(subset=['과목코드', '개설학과'])
    d['학기'] = sem
    return d


cur_all = pd.concat([load_cur(A + f, k) for k, f in CURS.items()], ignore_index=True)
# 같은 과목코드·학과는 최신 학기 1건만 (과목명·학년·이수구분은 최신 기준)
cur = (cur_all.sort_values('학기')
       .groupby(['과목코드', '개설학과'], as_index=False)
       .agg(개설대학=('개설대학', 'last'), 주관부서=('주관부서', 'last'), 학년=('학년', 'last'),
            이수구분=('이수구분', 'last'), 과목명=('과목명', 'last'), 학점=('학점', 'last'),
            과정=('과정', 'last'), 학기=('학기', lambda x: ','.join(sorted(set(x))))))

# 접두어(코드 앞 4자리) → 학과 (기본 학과만, 학부/대학원 분리)
base = cur[~cur['개설대학'].isin(EXCL_COLLEGE)].assign(p=lambda x: x['과목코드'].str[:4])
pref = {}
for (p, lvl), g in base.groupby(['p', '과정']):
    depts = sorted(set(g['개설학과']))
    pref.setdefault(p, {})[lvl] = depts


xb = cur[cur['개설대학'].isin(EXCL_COLLEGE) & (cur['과정'] == '학부')].assign(p=lambda x: x['과목코드'].str[:4])
pref_x = xb.groupby('p')['개설학과'].agg(lambda x: '/'.join(sorted(set(x)))).to_dict()


def infer(code, gubun):
    p = code[:4]
    if p in COMMON:
        return COMMON[p], '학부', '접두어(공통)'
    info = pref.get(p, {})
    if '학부' in info and len(info['학부']) == 1:
        return info['학부'][0], '학부', '접두어'
    if info and '학부' not in info:
        return '/'.join(sum(info.values(), [])), '대학원', '접두어'
    fu = pref_x.get(p)
    if fu:
        return fu, '학부', '접두어(융합·소단위)'
    if gubun in GYO:
        return '교양', '학부', '이수구분'
    return None, None, '미분류'


# ---- course_code: 코드 단위 ----
codes = (off.sort_values('학기').groupby('과목코드')
         .agg(과목명=('과목명', 'last'), 학점=('학점', 'last'), 이수구분=('이수구분', 'last'),
              학년=('학년', 'last'), 개설학기=('학기', lambda x: ','.join(sorted(set(x)))),
              분반수=('분반', 'count'), 교수=('담당교수', lambda x: ', '.join(sorted(set(', '.join(x).split(', ')) - {''}))))
         .reset_index())
only = cur[~cur['과목코드'].isin(set(codes['과목코드']))].groupby('과목코드').agg(
    과목명=('과목명', 'first'), 학점=('학점', 'first'), 이수구분=('이수구분', 'first'), 학년=('학년', 'first')).reset_index()
only['개설학기'] = '교육과정만(미개설)'
only['분반수'] = 0
only['교수'] = ''
codes = pd.concat([codes, only], ignore_index=True)
cur_code = cur.groupby('과목코드').agg(과정=('과정', lambda x: '학부' if '학부' in set(x) else x.iloc[0])).reset_index()
codes = codes.merge(cur_code, on='과목코드', how='left')

rows = []
for r in codes.itertuples():
    d, lvl, src = infer(r.과목코드, r.이수구분)
    if pd.notna(r.과정):
        lvl = '학부' if r.과정 == '학부' else '대학원'
    rows.append((d, lvl, src))
codes[['대표학과', '과정구분', '학과출처']] = rows

# ---- course_dept (N:M): 교육과정에 있으면 그것, 없으면 추론 학과 ----
cd_cur = cur[['과목코드', '개설대학', '개설학과', '학년', '학기', '이수구분']].assign(출처='교육과정')
cd_cur['기본학과'] = ~cd_cur['개설대학'].isin(EXCL_COLLEGE)
in_cur = set(cd_cur[cd_cur['기본학과']]['과목코드'])   # 기본 학과 소속이 확인된 코드 (융합전공에만 있으면 접두어 학과도 추가)
cd_inf = codes[~codes['과목코드'].isin(in_cur) & codes['대표학과'].notna() & (codes['대표학과'] != '교양')]
cd_inf = pd.DataFrame({'과목코드': cd_inf['과목코드'], '개설대학': None, '개설학과': cd_inf['대표학과'],
                       '학년': cd_inf['학년'], '학기': cd_inf['개설학기'], '이수구분': cd_inf['이수구분'],
                       '출처': cd_inf['학과출처'], '기본학과': True})
course_dept = pd.concat([cd_cur, cd_inf], ignore_index=True)

# ---- course: 정규화한 과목명 단위 (학부만) ----
codes['개설여부'] = codes['분반수'].fillna(0).astype(int) > 0
# 선택 후보(course)는 학부 + 6개 학기 중 1번 이상 개설된 과목만. 미개설 코드는 course_code에만 남김
ug = codes[(codes['과정구분'] == '학부') & codes['개설여부']].copy()
ug['정규명'] = ug['과목명'].map(norm)
course = (ug.groupby('정규명')
          .agg(과목명=('과목명', 'first'), 과목코드수=('과목코드', 'nunique'),
               과목코드=('과목코드', lambda x: ', '.join(sorted(x))),
               학과=('대표학과', lambda x: ', '.join(sorted(set(x.dropna())))))
          .reset_index().sort_values('과목명'))
course.insert(0, 'course_id', ['C%05d' % i for i in range(1, len(course) + 1)])
_dm = course_dept[course_dept['기본학과']].groupby('과목코드')['개설학과'].agg(set)
course['학과'] = course['과목코드'].map(lambda cs: ', '.join(sorted(set().union(*[_dm.get(c, set()) for c in cs.split(', ')])))
                                   ) .where(lambda x: x != '', course['학과'])
course['직무키워드'] = None          # L2: 다음 단계에서 채움
course['수업특징_30자'] = None       # L3: 선택
ug = ug.merge(course[['정규명', 'course_id']], on='정규명')
codes = codes.merge(ug[['과목코드', 'course_id']], on='과목코드', how='left')

# ---- 트랙 ----
def track(depts):
    cc = course_dept[course_dept['개설학과'].isin(depts)]['과목코드']
    t = codes[codes['과목코드'].isin(cc) & codes['course_id'].notna()]
    t = t.merge(course_dept[course_dept['개설학과'].isin(depts)]
                .groupby('과목코드')['개설학과'].agg(lambda x: ', '.join(sorted(set(x)))).rename('트랙학과'),
                on='과목코드')
    g = (t.groupby('course_id')
         .agg(과목명=('과목명', 'first'), 트랙학과=('트랙학과', lambda x: ', '.join(sorted(set(', '.join(x).split(', '))))),
              학년=('학년', lambda x: ', '.join(sorted(set(x.dropna())))),
              이수구분=('이수구분', lambda x: ', '.join(sorted(set(x.dropna())))),
              개설학기=('개설학기', lambda x: ','.join(sorted(set(','.join(x).split(','))))),
              과목코드=('과목코드', lambda x: ', '.join(sorted(x)))).reset_index())
    return g.sort_values(['트랙학과', '학년', '과목명'])

ta, tb = track(TRACK_A), track(TRACK_B)
offering = off[['학기', '과목코드', '분반', '과목명', '담당교수', '학년', '이수구분', '학점', '수업시간', '강의구분', '수강정원', '수강인원']]

summary = pd.DataFrame([
    ('강좌 행 (6개 학기)', len(off)),
    ('과목코드 전체', len(codes)),
    ('  └ 학부', (codes['과정구분'] == '학부').sum()),
    ('  └ 대학원', (codes['과정구분'] == '대학원').sum()),
    ('  └ 미분류 (대학원 추정 등)', codes['과정구분'].isna().sum()),
    ('학부 과목코드 중 개설된 것', ((codes['과정구분'] == '학부') & codes['개설여부']).sum()),
    ('학부 과목코드 중 미개설 (후보 제외)', ((codes['과정구분'] == '학부') & ~codes['개설여부']).sum()),
    ('대표 과목 = 선택 후보 (학부·개설, 과목명 통합)', len(course)),
    ('트랙 A 경영·SW 대표 과목', len(ta)),
    ('트랙 B 반도체 대표 과목', len(tb)),
], columns=['항목', '값'])

unk = codes[codes['과정구분'].isna()][['과목코드', '과목명', '이수구분', '학년', '개설학기', '교수']]

con = sqlite3.connect(OUT + 'cbnu_courses.sqlite')
for name, df in [('course', course), ('course_code', codes), ('course_dept', course_dept),
                 ('offering', offering), ('track_a', ta), ('track_b', tb)]:
    df.to_sql(name, con, if_exists='replace', index=False)
con.close()

with pd.ExcelWriter(OUT + 'cbnu_courses.xlsx') as w:
    for name, df in [('요약', summary), ('트랙A_경영SW', ta), ('트랙B_반도체', tb), ('course', course),
                     ('course_code', codes), ('course_dept', course_dept), ('offering', offering), ('미분류', unk)]:
        df.to_excel(w, sheet_name=name, index=False)

print(summary.to_string(index=False))
print(ta.groupby('트랙학과').size().sort_values(ascending=False).head(15).to_string())
print(tb.groupby('트랙학과').size().sort_values(ascending=False).head(15).to_string())
print(unk['이수구분'].value_counts().to_string())
