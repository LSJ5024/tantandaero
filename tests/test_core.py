"""LLM·네트워크 없이 도는 기본 테스트:  python -m pytest -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app  # noqa: E402
from draft import build_template, j  # noqa: E402
from matcher import Matcher, min_edu, required_certs  # noqa: E402

DB = str(Path(__file__).resolve().parents[1] / 'data' / 'cbnu.sqlite')
M = Matcher(DB)


def test_required_certs():
    assert required_certs('우대 전산세무1급 필수 전산세무2급') == (['전산세무2급'], [])
    assert required_certs('필수 자동차운전면허2종보통') == ([], ['자동차운전면허2종보통'])


def test_min_edu_range():
    assert min_edu('대졸(2~3년)~석사') == 4
    assert min_edu('학력무관') == 0


def test_josa():
    assert j('모델링', '을를') == '모델링을' and j('분석', '을를') == '분석을' and j('A+', '으로') == 'A+로'


def test_course_search_hides_blocked():
    names = [c['과목명'] for c in M.search_courses('미래설계')]
    assert '미래설계준비' not in names


def test_match_scores_and_ineligible():
    cid = M.search_courses('품질경영')[0]['course_id']
    r = M.match({'courses': [cid], 'interests': [], 'tracks': ['T2'], 'certs': [], 'edu': 3, 'regions': []},
                include_ineligible=True)
    assert r['results'] and 0 <= r['results'][0]['score'] <= 100
    assert all(x['eligible'] for x in r['results'])
    assert any('학력' in ' '.join(x['reasons_no']) for x in r['ineligible'])   # 고졸이면 대졸 요구 공고는 지원 불가


def test_draft_needs_only_course_inputs():
    post = {'company': 'A사', 'title': '[박람회] 품질관리 채용', '직무키워드': 'J202 품질관리'}
    r = {'C1': {'reasons': ['output'], 'title': '공정 데이터 분석'}}      # 역할·도구·결과는 비워 둠
    sec = build_template(post, {'certs': []}, ['C1'], {'C1': '품질경영'}, r)
    text = ' '.join(sec.values())
    assert '[직접 입력' not in text and '[박람회]' not in text
    assert '프로젝트 경험' in sec and '공정 데이터 분석' in sec['프로젝트 경험']
    sec2 = build_template(post, {'certs': []}, ['C1'], {'C1': '품질경영'}, {})
    assert '프로젝트 경험' not in sec2 and '[직접 입력' not in ' '.join(sec2.values())


def test_api_flow():
    c = app.test_client()
    assert c.get('/api/health').json['ok']
    cid = c.get('/api/courses?q=공급사슬').json[0]['course_id']
    m = c.post('/api/match', json={'courses': [cid], 'tracks': ['T2'], 'edu': 5}).json
    pid = m['results'][0]['posting_id']
    d = c.post('/api/draft', json={'courses': [cid], 'posting_id': pid, 'edu': 5}).json
    assert list(d['sections']) == ['지원 동기', '직무 역량', '입사 후 포부']
    w = c.post('/api/docx', json={'title': 't', 'sections': d['sections']})
    assert w.status_code == 200 and w.data[:2] == b'PK'
