"""과목 학습 주제(강의계획서 대체) 조회·생성
우선순위: DB course_syllabus(강의계획서 > 추정) → 메모리 캐시 → LLM 즉석 추정(키가 있을 때)
"""
import json
import sqlite3

import llm

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


class Syllabus:
    def __init__(self, db_path, courses):
        self.db_path, self.courses, self.mem = db_path, courses, {}
        try:
            con = sqlite3.connect(db_path)
            for cid, s, t, src in con.execute('select course_id, 개요, 주제, 출처 from course_syllabus'):
                self.mem[cid] = {'개요': s, '주제': json.loads(t), '출처': src}
            con.close()
        except sqlite3.Error:
            pass

    def get(self, ids, generate=True):
        out = {c: self.mem[c] for c in ids if c in self.mem}
        miss = [c for c in ids if c not in out and c in self.courses]
        if miss and generate and llm.status()['configured']:
            lines = '\n'.join(f"{c}: {self.courses[c]['과목명']} ({(self.courses[c]['학과'] or '').split(',')[0]})"
                              for c in miss)
            try:
                res = llm.parse_json(llm.call([{'role': 'system', 'content': PROMPT},
                                               {'role': 'user', 'content': lines}], llm.config(), timeout=40))
                for c in miss:
                    if valid(res.get(c)):
                        rec = {'개요': res[c]['개요'].strip(), '주제': [x.strip() for x in res[c]['주제']],
                               '출처': '추정(강의명 기반)'}
                        self.mem[c] = out[c] = rec
                        self._save(c, rec)
            except Exception:
                pass                                     # 실패하면 주제 없이 진행
        return out

    def _save(self, cid, rec):
        try:                                             # 읽기 전용 배포 환경이면 메모리 캐시만 사용
            con = sqlite3.connect(self.db_path)
            con.execute('create table if not exists course_syllabus '
                        '(course_id text primary key, 개요 text, 주제 text, 출처 text)')
            con.execute('insert or ignore into course_syllabus values (?,?,?,?)',
                        (cid, rec['개요'], json.dumps(rec['주제'], ensure_ascii=False), rec['출처']))
            con.commit()
            con.close()
        except sqlite3.Error:
            pass
