"""탄탄대로 – 충북대 수강 과목 기반 채용 매칭·지원서 서비스 (Flask)
실행: python app.py  →  http://localhost:5000
"""
import os
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

import llm  # noqa: E402  (load_env 이후에 읽어야 환경변수 반영)
from draft import build_template, clean_title, to_docx
from matcher import EDU_NAME, Matcher
from syllabus import Syllabus

BASE = Path(__file__).parent


def load_env(path=BASE / '.env'):
    """로컬 실행용 .env 읽기 (배포 환경에서는 서비스의 환경변수 설정을 사용)"""
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.split('#', 1)[0].strip()
            if '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
app = Flask(__name__, static_folder=str(BASE / 'static'))
app.json.sort_keys = False   # 지원서 항목 순서 유지
M = Matcher(str(BASE / 'data' / 'cbnu.sqlite'))
SYL = Syllabus(str(BASE / 'data' / 'cbnu.sqlite'), M.courses)


def profile_from(body):
    return {
        'courses': body.get('courses', [])[:10],
        'interests': body.get('interests', []),
        'tracks': body.get('tracks', [])[:2],
        'certs': body.get('certs', []),
        'edu': int(body.get('edu', 5)),
        'regions': body.get('regions', []),
        'today': body.get('today') or date.today().isoformat(),
    }


@app.get('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.get('/api/options')
def options():
    tracks = []
    for t in M.tracks:
        kws = [{'kw_id': k, '키워드': v['키워드'], '설명': v['설명'], '자격증': v['대표_자격증']}
               for k, v in M.kw.items() if v['직렬'] == t['직렬']]
        tracks.append({'track_id': t['track_id'], '직렬': t['직렬'], '트랙': t['트랙'], 'keywords': kws})
    regions = sorted({p['시도'] for p in M.posts.values() if p.get('시도')})
    return jsonify({'tracks': tracks, 'certs': M.cert_options(), 'regions': regions,
                    'edu': [{'code': k, 'name': v} for k, v in EDU_NAME.items() if k >= 3],
                    'snapshot': {'postings': len(M.posts), 'courses': sum(1 for c in M.courses.values() if c['선택가능'])}})


@app.get('/api/courses')
def courses():
    return jsonify(M.search_courses(request.args.get('q', '')))


@app.get('/api/syllabus')
def syllabus():
    ids = [x for x in request.args.get('ids', '').split(',') if x][:10]
    return jsonify(SYL.get(ids))


@app.post('/api/match')
def match():
    b = request.get_json(force=True)
    return jsonify(M.match(profile_from(b), sort=b.get('sort', 'score'), cb_first=bool(b.get('cb_first')),
                           include_ineligible=bool(b.get('include_ineligible'))))


@app.post('/api/draft')
def draft():
    b = request.get_json(force=True)
    prof = profile_from(b)
    pid = b['posting_id']
    S, src = M.strengths(prof)
    post = M.score_one(M.posts[pid], prof, S, src)
    names = {c: M.courses[c]['과목명'] for c in prof['courses'] if c in M.courses}
    picked = [c for c in b.get('picked', []) if c in names][:3]
    if not picked:   # 공고 키워드와 겹치는 과목 우선 추천
        hit = {n for m in post['match'] for n in m['과목']}
        picked = [c for c, n in names.items() if n in hit][:3] or list(names)[:2]
    reasons, extra = dict(b.get('reasons', {})), b.get('extra', {})
    syl = SYL.get(picked)
    for c in picked:                                     # 화면에서 주제를 안 보냈으면 강의계획서(추정) 주제 사용
        r = dict(reasons.get(c, {}))
        if 'topics' not in r and c in syl:
            r['topics'] = syl[c]['주제']
        if c in syl:
            r['개요'] = syl[c]['개요']
        reasons[c] = r
    template = build_template(post, prof, picked, names, reasons, extra)
    facts = {
        '회사': post['company'], '공고': clean_title(post['title']),
        '직무': ((post.get('직무키워드') or '').split(',')[0].split(' ', 1)[-1].replace('(부)', '').strip()),
        '과목': [{'과목명': names[c], **{k: v for k, v in reasons.get(c, {}).items() if v}} for c in picked],
        '자격증': prof['certs'], '추가': {k: v for k, v in extra.items() if v},
    }
    sections, info = (llm.polish(template, facts) if b.get('use_llm', True)
                      else (template, {'used': False, 'reason': '템플릿 선택'}))
    return jsonify({'post': post, 'picked': picked, 'sections': sections, 'template': template, 'llm': info})


@app.post('/api/docx')
def docx():
    b = request.get_json(force=True)
    buf = to_docx(b.get('title', '지원서 초안'), b.get('sections', {}))
    return send_file(buf, as_attachment=True, download_name='탄탄대로_지원서_초안.docx',
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


@app.get('/api/health')
def health():
    return jsonify({'ok': True, 'postings': len(M.posts), 'llm': llm.status()})   # 키 값은 노출하지 않음


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
