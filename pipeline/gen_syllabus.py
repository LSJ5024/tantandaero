"""강의계획서 대체 데이터: 과목명·개설학과로 '일반적인 강의계획서의 학습 주제'를 추정해 저장
- 출처 = '추정(강의명 기반)'. 실제 강의계획서를 확보하면 같은 테이블에 출처 = '강의계획서'로 덮어쓴다.
- 결과: data/cbnu.sqlite 의 course_syllabus(course_id, 개요, 주제(JSON), 출처)
사용: LLM_PROVIDER/LLM_API_KEY 환경변수 설정 후  python pipeline/gen_syllabus.py [최대과목수]
"""
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import llm  # noqa: E402

DB = ROOT / 'data' / 'cbnu.sqlite'
CACHE = ROOT / 'pipeline' / 'syllabus_cache.jsonl'
TRACK_DEPTS = ['경영정보학과', '경영학부', '국제경영학과', '소프트웨어학부', '컴퓨터공학과', '정보통계학과', '융합소프트웨어전공',
               '화학공학과', '전자공학과', '전자공학부', '반도체공학부', '시스템반도체학과', '정보통신공학부', '전기공학부',
               '공업화학과', '신소재공학과']
BATCH = 20

PROMPT = """너는 한국 4년제 대학의 교육과정 담당자다. 강의계획서가 없는 과목들에 대해, 과목명과 개설학과만 보고
그 과목의 '일반적인 강의계획서'에 실릴 내용을 추정해라.
규칙:
- 주제: 그 과목에서 보편적으로 다루는 핵심 학습 주제 4~6개. 각 15자 이내의 명사구 (예: "수요예측 기법", "관리도와 공정능력").
- 개요: 과목을 한 문장으로 설명, 35자 이내, "~를 다루는 과목" 형태.
- 특정 교수·교재·소프트웨어 제품명·프로젝트·성적 정보는 쓰지 않는다. 과목명만으로 알 수 없는 세부사항을 단정하지 않는다.
- 과목명이 모호하면(세미나, 특강, 캡스톤 등) 개설학과의 일반적인 범위로 보수적으로 쓴다.
출력: JSON 객체 하나. {"과목ID": {"개요": "...", "주제": ["...", ...]}, ...}"""


def valid(item):
    if not isinstance(item, dict):
        return False
    s, t = item.get('개요'), item.get('주제')
    return (isinstance(s, str) and 5 <= len(s) <= 45 and isinstance(t, list) and 3 <= len(t) <= 6
            and all(isinstance(x, str) and 2 <= len(x) <= 20 for x in t))


def main(limit=None):
    con = sqlite3.connect(DB)
    rows = con.execute("select course_id, 과목명, 학과 from course where 매핑상태='매핑'").fetchall()
    rows.sort(key=lambda r: (not any(d in (r[2] or '') for d in TRACK_DEPTS), r[0]))
    done = {}
    if CACHE.exists():
        for ln in CACHE.read_text(encoding='utf-8').splitlines():
            d = json.loads(ln)
            done[d['course_id']] = d
    todo = [r for r in rows if r[0] not in done][: limit or None]
    cfg = llm.config()
    print('todo', len(todo), 'done', len(done), flush=True)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        lines = '\n'.join(f"{cid}: {name} ({(dept or '').split(',')[0]})" for cid, name, dept in chunk)
        msgs = [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': lines}]
        for attempt in range(4):
            try:
                out = llm.parse_json(llm.call(msgs, cfg, timeout=90))
                break
            except Exception as e:
                print('retry', attempt, str(e)[:120], flush=True)
                time.sleep(20)
        else:
            continue
        with CACHE.open('a', encoding='utf-8') as f:
            for cid, name, dept in chunk:
                it = out.get(cid)
                if valid(it):
                    rec = {'course_id': cid, '개요': it['개요'].strip(), '주제': [x.strip() for x in it['주제']]}
                    done[cid] = rec
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(i + len(chunk), '/', len(todo), 'saved', len(done), flush=True)
        time.sleep(8)                                   # 무료 한도(분당 토큰) 보호
    con.execute('create table if not exists course_syllabus (course_id text primary key, 개요 text, 주제 text, 출처 text)')
    con.executemany("insert into course_syllabus values (?,?,?,?) on conflict(course_id) do update set "
                    "개요=excluded.개요, 주제=excluded.주제, 출처=excluded.출처 where course_syllabus.출처 != '강의계획서'",
                    [(d['course_id'], d['개요'], json.dumps(d['주제'], ensure_ascii=False), '추정(강의명 기반)')
                     for d in done.values()])
    con.commit()
    print('db rows', con.execute('select count(*) from course_syllabus').fetchone()[0])


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
