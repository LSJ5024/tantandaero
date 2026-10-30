"""LLM 과목 매핑 결과(jsonl) + 기존 매핑(map/m01~m04) → map/m05.txt
- 기존에 매핑된 과목: 신규 직렬 키워드를 '부'로 덧붙임 (확신도 H/M만, 최대 2개)
- 매핑이 없던 과목: LLM 결과를 그대로 주/부로 사용
- 기존 선택불가(X) 과목은 건드리지 않음
- 노이즈 줄이기: 키워드의 직렬이 그 학과의 주요 진출 직렬(map_llm.DEPT_HINT)에 없으면
  기존 과목에는 추가하지 않고, 미매핑 과목은 확신도 H일 때만 채택
사용: python pipeline/merge_course_map.py <map_dir> <course_map_new.jsonl> <db>
"""
import glob, json, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from map_llm import hint  # noqa: E402

MAP, NEW, DB = sys.argv[1], sys.argv[2], sys.argv[3]
con = sqlite3.connect(DB)
dept = dict(con.execute('select course_id, 학과 from course'))
track_of = dict(con.execute('select kw_id, 직렬 from job_keyword'))


def fits(cid, k):
    return track_of[k] in hint(dept.get(cid, ''))
old = {}
for f in sorted(glob.glob(MAP + '/m0[1-4].txt')):
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            p = ln.split('|'); old[p[0]] = p

out, n_add, n_new = [], 0, 0
for ln in open(NEW, encoding='utf-8'):
    r = json.loads(ln)
    cid = r['id'][1:]                         # 'C00043' → '00043'
    if not r['main']:
        continue
    o = old.get(cid)
    if o and o[1] == 'X':
        continue
    if o:
        if r['conf'] not in ('H', 'M'):
            continue
        subs = [s for s in o[2].split(',') if s]
        add = [k for k in [r['main']] + r['sub'] if k not in subs and k != o[1] and fits(r['id'], k)][:2]
        if not add:
            continue
        out.append(f"{cid}|{o[1]}|{','.join(subs + add)}|{o[3]}"); n_add += 1
    else:
        if not fits(r['id'], r['main']) and r['conf'] != 'H':
            continue
        out.append(f"{cid}|{r['main']}|{','.join(r['sub'])}|{r['conf']}"); n_new += 1

with open(MAP + '/m05.txt', 'w', encoding='utf-8') as f:
    f.write('# 2차 확장(2026-10-30): 신규 직렬 T6~T12 LLM 매핑 초안 (id|주|부|확신도)\n')
    f.write('\n'.join(sorted(out)) + '\n')
print('기존 과목에 신규 부키워드 추가', n_add, '/ 새로 매핑된 과목', n_new)
