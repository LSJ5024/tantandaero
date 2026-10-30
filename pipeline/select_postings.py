"""수집 목록(list.json)에서 직렬별로 검색어를 고르게 돌며 공고 선택 → select.json
사용: python pipeline/select_postings.py <w24_dir> <직렬당 개수> [기존 postings.json ...]
"""
import json, re, sys
from collections import defaultdict

W, N = sys.argv[1], int(sys.argv[2])
seen = set()
for f in sys.argv[3:]:
    seen |= {p['id'] for p in json.load(open(f, encoding='utf-8'))}
JUNK = re.compile(r'알바|아르바이트|단순|일용|간병|요양보호|청소|미화|경비|배달|운전기사|주방|조리원|판매원|캐셔|텔레마케|'
                  r'단기|시간제|파트타임|포장|검품|상하차')

rows = json.load(open(W + '/list.json', encoding='utf-8'))
by = defaultdict(lambda: defaultdict(list))
for r in rows:
    if r['id'] in seen or JUNK.search(r['title']):
        continue
    by[r['track_query']][r['query']].append(r)

sel = []
for track, qs in by.items():
    picked, i = [], 0
    while len(picked) < N and any(i < len(v) for v in qs.values()):
        for q, v in qs.items():
            if i < len(v) and len(picked) < N:
                picked.append(v[i]['id'])
        i += 1
    sel += picked
    print(track, len(picked), {q: len(v) for q, v in qs.items()})
json.dump(sel, open(W + '/select.json', 'w'), ensure_ascii=False)
print('selected', len(sel))
