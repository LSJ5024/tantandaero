"""LLM 공고 매핑 결과(jsonl) + 기존 공고 매핑(postmap/p01~p03) → postmap/p04.txt
- 기존 공고: 기존 주/부 유지, 신규 직렬(T6~T12) 키워드만 '부'로 최대 2개 추가 (기존 X는 유지)
- 신규 공고: LLM 결과 그대로 (X = 제외)
사용: python pipeline/merge_posting_map.py <postmap_dir> <posting_map_new.jsonl> <new_tracks_kw_ids(쉼표)>
"""
import glob, json, sys

PM, NEW, NEWKW = sys.argv[1], sys.argv[2], set(sys.argv[3].split(','))
old = {}
for f in sorted(glob.glob(PM + '/p0[1-3].txt')):
    for ln in open(f, encoding='utf-8'):
        ln = ln.strip()
        if ln and not ln.startswith('#'):
            q = ln.split('|'); old[q[0]] = q

out, n_add, n_new, n_x = [], 0, 0, 0
for ln in open(NEW, encoding='utf-8'):
    r = json.loads(ln)
    o = old.get(r['id'])
    if o:
        if o[1] == 'X' or not r['main']:
            continue
        subs = [s for s in (o[2] if len(o) > 2 else '').split(',') if s]
        add = [k for k in [r['main']] + r['sub'] if k in NEWKW and k not in subs and k != o[1]][:2]
        if add:
            out.append(f"{r['id']}|{o[1]}|{','.join(subs + add)}"); n_add += 1
    elif r.get('x') or not r['main']:
        out.append(f"{r['id']}|X"); n_x += 1
    else:
        out.append(f"{r['id']}|{r['main']}|{','.join(r['sub'])}"); n_new += 1

with open(PM + '/p04.txt', 'w', encoding='utf-8') as f:
    f.write('# 2차 확장(2026-10-30): LLM 공고 매핑 (posting_id|주|부)  또는 posting_id|X\n')
    f.write('\n'.join(out) + '\n')
print('기존 공고에 신규 부키워드 추가', n_add, '/ 신규 공고 포함', n_new, '/ 제외', n_x)
