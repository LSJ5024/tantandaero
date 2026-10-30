"""과목 → 직무 키워드 매핑 적용
입력: map/m*.txt  (id|주|부1,부2|확신도  또는  id|X)
출력: DB에 course_keyword 테이블, course.직무키워드/선택가능/매핑상태 갱신 + 검수용 엑셀
"""
import glob, sys, sqlite3
import pandas as pd

S = sys.argv[1]
con = sqlite3.connect(S + '/out/cbnu_courses.sqlite')
course = pd.read_sql('select * from course', con)
kw = pd.read_sql('select kw_id, 직렬, 키워드 from job_keyword', con)
kname = dict(zip(kw['kw_id'], kw['키워드']))

ent = {}
for f in sorted(glob.glob(S + '/map/m*.txt')):
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        p = ln.split('|')
        ent['C' + p[0]] = p          # 뒤 파일이 앞을 덮어씀

ck, blocked = [], set()
for cid, p in ent.items():
    if p[1] == 'X':
        blocked.add(cid); continue
    conf = {'H': '상', 'M': '중', 'L': '하'}[p[3]]
    ck.append((cid, p[1], '주', conf))
    for k in filter(None, p[2].split(',')):
        ck.append((cid, k, '부', conf))
ck = pd.DataFrame(ck, columns=['course_id', 'kw_id', '구분', '확신도'])

def label(cid):
    g = ck[ck['course_id'] == cid]
    return ', '.join(f"{r.kw_id} {kname[r.kw_id]}" + ('' if r.구분 == '주' else '(부)') for r in g.itertuples())

lab = ck.groupby('course_id').apply(lambda g: ', '.join(
    f"{r.kw_id} {kname[r.kw_id]}" + ('' if r.구분 == '주' else '(부)') for r in g.itertuples()), include_groups=False)
course['직무키워드'] = course['course_id'].map(lab)
course['선택가능'] = ~course['course_id'].isin(blocked)
course['매핑상태'] = '해당없음'
course.loc[course['직무키워드'].notna(), '매핑상태'] = '매핑'
course.loc[course['course_id'].isin(blocked), '매핑상태'] = '선택불가'
conf1 = ck[ck['구분'] == '주'].set_index('course_id')['확신도']
course['확신도'] = course['course_id'].map(conf1)

course.to_sql('course', con, if_exists='replace', index=False)
ck.to_sql('course_keyword', con, if_exists='replace', index=False)

# ---- 검수용 엑셀 ----
mapped = course[course['매핑상태'] == '매핑'][['course_id', '과목명', '학과', '직무키워드', '확신도']]
stat = (ck.merge(kw, on='kw_id').groupby(['kw_id', '직렬', '키워드'])
        .agg(주=('구분', lambda x: (x == '주').sum()), 부=('구분', lambda x: (x == '부').sum())).reset_index())
summ = course['매핑상태'].value_counts().rename_axis('상태').reset_index(name='과목수')
summ2 = mapped['확신도'].value_counts().rename_axis('확신도(주 키워드)').reset_index(name='과목수')
with pd.ExcelWriter(S + '/out/course_keyword_review.xlsx') as w:
    summ.to_excel(w, sheet_name='요약', index=False)
    summ2.to_excel(w, sheet_name='요약', index=False, startrow=len(summ) + 2)
    stat.to_excel(w, sheet_name='키워드별_과목수', index=False)
    mapped.sort_values(['확신도', '학과']).to_excel(w, sheet_name='매핑_전체', index=False)
    course[course['매핑상태'] == '선택불가'][['course_id', '과목명', '학과']].to_excel(w, sheet_name='선택불가', index=False)
con.close()
print(summ.to_string(index=False)); print(summ2.to_string(index=False))
print(stat.to_string(index=False))
