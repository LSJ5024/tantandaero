"""수집한 공고 → 구조화 → DB(job_posting) 적재
키워드 매핑은 postmap/p*.txt (id|주|부1,부2|직렬)에서 읽음. 없으면 비워 둠.
"""
import glob, json, re, sqlite3, sys
import pandas as pd

S = sys.argv[1]
P = json.load(open(S + '/w24/postings.json'))
try:                                                     # 2차 확장 수집분 (신규 직렬 T6~T12)
    _ids = {p['id'] for p in P}
    P += [p for p in json.load(open(S + '/w24b/postings.json')) if p['id'] not in _ids]
except FileNotFoundError:
    pass

SIDO = ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '충청북도', '충청남도', '전라북도',
        '전북', '전라남도', '경상북도', '경상남도', '제주', '충북', '충남', '전남', '경북', '경남']
SIDO_N = {'충청북도': '충북', '충청남도': '충남', '전라북도': '전북', '전북특별자치도': '전북', '전라남도': '전남',
          '경상북도': '경북', '경상남도': '경남', '강원특별자치도': '강원', '제주특별자치도': '제주'}


def region(addr):
    a = (addr or '').strip()
    first = a.replace(',', ' ').split(' ')[0] if a else ''
    sido = None
    for k, v in SIDO_N.items():
        if first.startswith(k): sido = v
    if first.startswith('전남광주'): sido = '전남광주'
    if not sido:
        for s in ['서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종', '경기', '강원', '제주', '충북', '충남', '전북', '전남', '경북', '경남']:
            if first.startswith(s): sido = s
    sgg = a.split(' ')[1] if len(a.split(' ')) > 1 else ''
    return sido, sgg


def salary(s):
    s = (s or '').replace(',', '')
    nums = [int(x) for x in re.findall(r'(\d+)\s*만원', s)]
    if '연봉' in s and nums: return min(nums)
    if '월급' in s and nums: return min(nums) * 12
    m = re.findall(r'(\d+)\s*원', s)
    if '시급' in s and m: return round(int(m[0]) * 209 * 12 / 10000)
    return None


def edu(s):
    s = s or ''
    for k, v in [('박사', 7), ('석사', 6), ('대졸(4년)', 5), ('대학졸업(4년)', 5), ('4년', 5), ('2~3년', 4), ('2∼3년', 4),
                 ('고졸', 3), ('무관', 0)]:
        if k in s: return v
    return None


def deadline(s):
    m = re.search(r'(\d{4})[.\-](\d{2})[.\-](\d{2})', s or '')
    return f'{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else None


def from_raw(raw, label, n=1):
    L = [x.strip() for x in (raw or '').split('\n')]
    for i, l in enumerate(L):
        if l == label and i + 1 < len(L):
            return ' '.join(L[i + 1:i + 1 + n])
    return None


rows = []
for p in P:
    d = dict(p.get('detail', {}))
    raw = d.get('_raw', '')
    if not p['id'].startswith('K'):                       # 외부 제공처(사람인·매칭플랫폼 등) 형식 보정
        d['학력'] = from_raw(raw, '학력') or d.get('학력')
        d['경력'] = from_raw(raw, '경력', 3) or d.get('경력')
        d['근무 예정지'] = from_raw(raw, '근무 예정지') or d.get('근무 예정지')
        d['임금 조건'] = from_raw(raw, '임금조건') or d.get('임금 조건')
        d['고용 형태'] = from_raw(raw, '고용형태') or d.get('고용 형태')
        per = from_raw(raw, '접수 기간', 3) or ''
        d['접수 마감일'] = per.split('~')[-1].strip() if '~' in per else per
    sido, sgg = region(d.get('근무 예정지'))
    rows.append({
        'posting_id': p['id'], 'company': p['company'], 'title': p['title'], 'url': p['url'],
        'track_query': p['track_query'], 'query': p['query'],
        '기업형태': ', '.join(p.get('labels', [])), '기업규모': d.get('기업규모'), '업종': d.get('업종'),
        '근로자수': d.get('근로자수'), '경력': d.get('경력'), '학력': d.get('학력'), '학력_코드': edu(d.get('학력')),
        '임금': d.get('임금 조건'), '연봉_만원_추정': salary(d.get('임금 조건')),
        '근무지': d.get('근무 예정지'), '시도': sido, '시군구': sgg, '충북여부': sido == '충북',
        '고용형태': d.get('고용 형태'), '모집직종': d.get('모집 직종'), '관련직종': d.get('관련 직종'),
        '직종키워드': d.get('직종 키워드'), '자격면허': d.get('자격 면허'), '전공': d.get('전공'),
        '컴퓨터활용': d.get('컴퓨터 활용 능력'), '우대조건': d.get('우대조건'), '기타우대': d.get('기타 우대사항'),
        '직무내용': d.get('직무내용'), '접수마감': d.get('접수 마감일'), '마감일': deadline(d.get('접수 마감일')),
        '등록일시': d.get('채용공고 등록일시'), '수집시각': p.get('collected_at'),
    })
df = pd.DataFrame(rows)

# 키워드 매핑
ent = {}
for f in sorted(glob.glob(S + '/postmap/p*.txt')):
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            q = ln.split('|'); ent[q[0]] = q
pk = []
for pid, q in ent.items():
    if q[1] == 'X': continue
    pk.append((pid, q[1], '주'))
    for k in filter(None, q[2].split(',')): pk.append((pid, k, '부'))
pk = pd.DataFrame(pk, columns=['posting_id', 'kw_id', '구분'])
df['포함여부'] = df['posting_id'].map(lambda x: '제외' if ent.get(x, [None, None])[1] == 'X' else ('포함' if x in ent else '미검토'))

con = sqlite3.connect(S + '/out/cbnu_courses.sqlite')
kw = pd.read_sql('select kw_id, 키워드 from job_keyword', con)
kn = dict(zip(kw['kw_id'], kw['키워드']))
lab = pk.groupby('posting_id').apply(lambda g: ', '.join(f"{r.kw_id} {kn[r.kw_id]}" + ('' if r.구분 == '주' else '(부)')
                                                           for r in g.itertuples()), include_groups=False) if len(pk) else {}
df['직무키워드_매핑'] = df['posting_id'].map(lab)
df.to_sql('job_posting', con, if_exists='replace', index=False)
pk.to_sql('posting_keyword', con, if_exists='replace', index=False)
con.close()
print(df['포함여부'].value_counts().to_string())
print(df['시도'].value_counts().head(12).to_string())
print('연봉 추정 있음', df['연봉_만원_추정'].notna().sum(), '마감일 있음', df['마감일'].notna().sum())
