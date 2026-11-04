"""LLM 안전장치 테스트 (실제 API를 부르지 않고 응답을 흉내 냄)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import llm  # noqa: E402

DRAFT = {'지원 동기': "A사의 품질관리 공고에 지원합니다. [직접 입력: 끌린 이유]",
         '직무 역량': "「품질경영」 수업에서 Python 등을 활용해 관리도 분석을 했습니다. [직접 입력: 결과·수치]",
         '경험과 성과': "[직접 입력: 수업 밖 경험]"}
FACTS = {'회사': 'A사', '공고': '품질관리 채용', '직무': '품질관리',
         '과목': [{'과목명': '품질경영', 'tools': 'Python', 'role': '관리도 분석', 'grade': 'A+'}]}
GOOD = {
    '지원 동기': [{'s': 'A사의 품질관리 채용 공고를 보고 지원합니다.', 'src': ['F01', 'F02']},
              {'s': '[직접 입력: 끌린 이유]', 'src': ['P1']}],
    '직무 역량': [{'s': '「품질경영」 수업에서 관리도 분석을 맡았습니다.', 'src': ['C1', 'C1R']},
              {'s': '이 과정에서 Python을 활용했습니다.', 'src': ['C1U']},
              {'s': '「품질경영」은 A+로 이수했습니다.', 'src': ['C1', 'C1G']},
              {'s': '[직접 입력: 결과·수치]', 'src': ['P2']}],
    '경험과 성과': [{'s': '[직접 입력: 수업 밖 경험]', 'src': ['P3']}],
}


def run(monkeypatch, *replies):
    monkeypatch.setenv('LLM_API_KEY', 'test')
    seq = iter(replies)
    monkeypatch.setattr(llm, 'call', lambda m, c, timeout=40, **kw: json.dumps(next(seq), ensure_ascii=False))
    return llm.polish(DRAFT, FACTS)


def edit(sec, i, **kw):
    out = json.loads(json.dumps(GOOD, ensure_ascii=False))
    out[sec][i].update(kw)
    return out


def test_no_key_uses_template(monkeypatch):
    monkeypatch.delenv('LLM_API_KEY', raising=False)
    out, info = llm.polish(DRAFT, FACTS)
    assert out == DRAFT and not info['used']


def test_good_reply_accepted(monkeypatch):
    out, info = run(monkeypatch, GOOD)
    assert info['used'] and '[직접 입력: 결과·수치]' in out['직무 역량'] and info['evidence']


def test_invented_number_rejected(monkeypatch):
    bad = edit('직무 역량', 1, s='Python으로 불량률을 30% 줄였습니다.')
    out, info = run(monkeypatch, bad, bad)
    assert out == DRAFT and '30%' in info['reason'] and info['tries'] == 2


def test_tool_must_match_cited_fact(monkeypatch):
    bad = edit('직무 역량', 0, s='「품질경영」 수업에서 Python으로 관리도 분석을 맡았습니다.')   # 근거 C1,C1R에는 Python 없음
    out, info = run(monkeypatch, bad, bad)
    assert out == DRAFT and 'python' in info['reason']


def test_placeholder_must_be_verbatim(monkeypatch):
    bad = edit('지원 동기', 1, s='[직접 입력: 끌린 이유]을 말씀드리겠습니다.')
    out, info = run(monkeypatch, bad, bad)
    assert out == DRAFT and '빈칸' in info['reason']


def test_banned_phrase_rejected(monkeypatch):
    bad = edit('직무 역량', 2, s='「품질경영」을 탁월한 성적인 A+로 이수했습니다.')
    out, info = run(monkeypatch, bad, bad)
    assert out == DRAFT and '탁월' in info['reason']


def test_unknown_course_and_id_rejected(monkeypatch):
    bad = edit('직무 역량', 0, s='「생산관리」에서도 관리도를 배웠습니다.')
    assert '과목명' in run(monkeypatch, bad, bad)[1]['reason']
    bad = edit('직무 역량', 0, src=['C9'])
    assert '근거 ID' in run(monkeypatch, bad, bad)[1]['reason']


def test_placeholder_only_section_stays(monkeypatch):
    bad = json.loads(json.dumps(GOOD, ensure_ascii=False))
    bad['경험과 성과'].insert(0, {'s': '다양한 경험을 쌓았습니다.', 'src': ['연결']})
    out, info = run(monkeypatch, bad, bad)
    assert out == DRAFT and '빈칸만' in info['reason']


def test_retry_fixes(monkeypatch):
    bad = edit('직무 역량', 1, s='Python으로 불량률을 30% 줄였습니다.')
    out, info = run(monkeypatch, bad, GOOD)
    assert info['used'] and info['tries'] == 2


def test_api_error_falls_back(monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'test')
    def boom(*a, **k):
        raise RuntimeError('HTTP 429: quota')
    monkeypatch.setattr(llm, 'call', boom)
    out, info = llm.polish(DRAFT, FACTS)
    assert out == DRAFT and '429' in info['reason']


def _T():
    return llm.fact_table({'회사': 'A사', '공고': '개발자', '직무': '백엔드 개발',
                           '과목': [{'과목명': '데이터 분석 프로그래밍', 'topics': ['데이터 전처리'], 'role': '시각화 담당'}],
                           '업무': ['측정 데이터 분석 기능 개발'], '회사소개': 'A사는 센서 전문 기업입니다.'})


def test_posting_facts_in_table():
    T = _T()
    assert T['J1'][1] == '측정 데이터 분석 기능 개발' and 'B2' in T


def test_no_invented_actions_or_bare_course_names():
    T, draft = _T(), {'직무 역량': 'x'}
    bad1 = {'직무 역량': [{'s': '「데이터 분석 프로그래밍」에서 데이터 전처리를 구현했습니다.', 'src': ['C1S']}]}
    assert '직접 한 일' in llm.validate(draft, bad1, T, {}, {})
    bad2 = {'직무 역량': [{'s': '데이터 분석 프로그래밍에서 데이터 전처리를 학습했습니다.', 'src': ['C1S']}]}
    assert '꺾쇠' in llm.validate(draft, bad2, T, {}, {})
    ok = {'직무 역량': [{'s': '「데이터 분석 프로그래밍」에서 다룬 데이터 전처리는 공고의 측정 데이터 분석 기능 개발 업무와 맞닿아 있습니다.',
                       'src': ['C1S', 'J1']},
                      {'s': '이 과목의 성과물에서 시각화 담당을 맡았습니다.', 'src': ['C1R']}]}
    assert llm.validate(draft, ok, T, {}, {}) is None


def test_strip_ids_from_text():
    out = llm.strip_ids({'a': [{'s': '공고의 J1 업무와 (C1S) 맞닿아 B2B', 'src': ['J1']}]}, {'J1': 1, 'C1S': 1, 'B2': 1})
    assert out['a'][0]['s'] == '공고의 업무와 맞닿아 B2B'
