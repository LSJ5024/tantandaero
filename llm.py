"""LLM 연결 (OpenAI 호환 Chat Completions API 하나로 Gemini · Groq · OpenAI 모두 지원)

환경변수
  LLM_PROVIDER   gemini | groq | openai | custom   (기본 groq)
  LLM_API_KEY    API 키 (필수, 코드·저장소에 넣지 말 것)
  LLM_MODEL      모델 이름 (생략하면 공급자별 기본값)
  LLM_BASE_URL   custom일 때 주소

방식: "근거 있는 문장" 생성
  사용자가 입력한 사실을 F01·C1T 같은 ID가 붙은 표로 만들어 주고,
  LLM은 문장마다 근거 ID를 달아 {"항목": [{"s": 문장, "src": [ID...]}]} 형태로만 답한다.
  서버가 문장 단위로 검사해서 하나라도 어기면 위반 내용을 알려 주고 1번 다시 쓰게 한다.
  그래도 실패하면 템플릿 초안을 쓰고 이유를 화면에 표시한다.

검사 항목 (validate)
  - 항목 이름·순서 유지, 항목당 문장 1~7개, 항목당 700자 이하
  - 근거 ID가 실제로 존재해야 함. 근거 없는 '연결' 문장은 항목당 1개, 45자 이하
  - [직접 입력: ...] 문장은 원래 항목에 원문 그대로, 독립된 한 문장으로 모두 남아 있어야 함
  - 문장 속 숫자·영문 단어는 그 문장이 인용한 사실 안에 있어야 함
  - 「과목명」은 입력한 과목만
  - 과장·평가 표현(공식적으로, 탁월한, 전문가, 성공적으로, 크게 기여 등)은 사실에 없으면 금지
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

PRESETS = {
    'gemini': {'base': 'https://generativelanguage.googleapis.com/v1beta/openai', 'model': 'gemini-flash-latest'},
    'groq': {'base': 'https://api.groq.com/openai/v1', 'model': 'openai/gpt-oss-120b'},
    'openai': {'base': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'},
}

SYSTEM = """너는 한국 대학생 자기소개서 초안을 쓰는 편집자다. 사용자는 이 초안을 거의 그대로 회사에 제출한다. 아래 규칙을 모두 지켜라.

[근거 규칙]
1. 모든 문장에는 src로 근거 ID를 단다. 근거는 [사실표]의 ID 또는 [빈칸표]의 ID만 쓸 수 있다.
2. 사실표에 없는 경험·수치·도구·성과·자격·수상·감정 경험을 쓰지 않는다. 사실을 부풀리거나 일반화하지 않는다.
   예) 사실이 "관리도 분석 담당"이면 "품질 개선을 이끌었습니다"라고 쓰지 않는다.
3. 회사에 대해서는 회사명과 공고명 외의 정보(업계 위상, 비전, 제품, 규모)를 쓰지 않는다.
4. 근거 없이 문장을 잇는 연결 문장은 항목당 최대 2개, 50자 이하로만 쓰고 src를 ["연결"]로 단다. 연결 문장에도 새로운 사실을 넣지 않는다.
4-1. '수업에서 다룬 주제'는 "학습했습니다/다뤘습니다/익혔습니다" 수준으로만 쓴다. 숙달·능숙·실무 경험이 있다고 쓰지 않는다.
4-2. 주제와 지원 직무의 연관성은 설명해도 된다(예: "관리도는 품질관리 업무의 기초입니다"). 단 회사의 실제 업무 내용을 단정하지 않는다.

[빈칸 규칙]
5. [빈칸표]의 문장은 원래 항목에, 글자 하나 바꾸지 않고, 앞뒤에 조사나 말을 붙이지 않은 독립된 한 문장으로 그대로 넣는다. src는 그 빈칸 ID 하나다.
6. 빈칸을 다른 말로 채우거나 지우지 않는다.

[표현 규칙]
7. 과장·평가 표현을 쓰지 않는다: 공식적으로, 탁월한, 뛰어난, 완벽한, 최고의, 전문가, 누구보다, 성공적으로, 크게 기여, 확신합니다, 반드시, 혁신적인.
8. 과목명은 「」 안에 사실표의 이름 그대로 쓴다.
9. 존댓말 평서문(~습니다)으로, 한 문장은 90자 이내로 쓴다. 근거가 충분하면 항목당 3~6문장, 200~450자로 충실하게 쓴다. 근거가 적은 항목은 짧아도 된다.
10-1. '프로젝트 경험' 항목이 있으면 성과물 제목·역할·결과(C?T, C?R, C?V)는 그 항목에만 쓰고 다른 항목에서 반복하지 않는다.
10. 항목 이름과 순서는 [초안]과 같게 유지한다. 빈칸만 있는 항목은 그 빈칸 문장 하나만 쓴다.

[출력]
JSON 객체 하나만 출력한다: {"항목 이름": [{"s": "문장", "src": ["ID"]}, ...], ...}"""

BANNED = ['공식적으로', '탁월', '뛰어난', '완벽', '최고의', '전문가', '누구보다', '성공적으로', '크게 기여', '확신',
          '반드시', '혁신적', '선도', '업계 최고', '글로벌 리더', '독보적', '숙달', '능숙', '전문적']
PH_RE = re.compile(r'\[직접 입력:[^\]]*\]')


def config():
    prov = os.environ.get('LLM_PROVIDER', 'groq').lower()
    p = PRESETS.get(prov, {})
    return {
        'provider': prov,
        'key': os.environ.get('LLM_API_KEY', ''),
        'base': (os.environ.get('LLM_BASE_URL') or p.get('base', '')).rstrip('/'),
        'model': os.environ.get('LLM_MODEL') or p.get('model', ''),
    }


def status():
    c = config()
    return {'configured': bool(c['key'] and c['base'] and c['model']), 'provider': c['provider'], 'model': c['model']}


def _tokens(text):
    """검증용: 숫자와 영문 단어(2글자 이상)"""
    t = PH_RE.sub(' ', str(text))
    return set(re.findall(r'\d+(?:[.,]\d+)?%?', t)) | {w.lower() for w in re.findall(r'[A-Za-z][A-Za-z+#.]{1,}', t)}


def fact_table(facts):
    """사용자 입력 → ID가 붙은 사실표 {ID: (설명, 값)}"""
    T = {'F01': ('회사명', facts.get('회사')), 'F02': ('공고명', facts.get('공고')),
         'F03': ('지원 직무', facts.get('직무')), 'F04': ('학교', '충북대학교')}
    names = {'grade': ('성적', 'G'), 'title': ('성과물 제목', 'T'), 'role': ('맡은 역할', 'R'),
             'tools': ('사용 도구·기법', 'U'), 'result': ('결과·수치', 'V'), 'learned': ('배운 내용', 'K')}
    for i, c in enumerate(facts.get('과목', []), 1):
        T[f'C{i}'] = ('수강 과목', c.get('과목명'))
        if c.get('topics'):
            T[f'C{i}S'] = (f"{c.get('과목명')} – 수업에서 다룬 주제(강의계획서)", ', '.join(c['topics']))
        if c.get('개요'):
            T[f'C{i}O'] = (f"{c.get('과목명')} – 과목 개요", c['개요'])
        for k, (label, suf) in names.items():
            if c.get(k):
                T[f'C{i}{suf}'] = (f"{c.get('과목명')} – {label}", c[k])
    if facts.get('자격증'):
        T['Q1'] = ('보유 자격증', ', '.join(facts['자격증']))
    for k, (fid, label) in {'motive': ('M1', '지원 동기(본인 작성)'), 'experience': ('E1', '수업 밖 경험(본인 작성)'),
                            'goal': ('G1', '입사 후 목표(본인 작성)')}.items():
        if (facts.get('추가') or {}).get(k):
            T[fid] = (label, facts['추가'][k])
    return {k: v for k, v in T.items() if v[1]}


def placeholder_table(draft):
    P, where = {}, {}
    for sec, text in draft.items():
        for ph in PH_RE.findall(text):
            pid = f'P{len(P) + 1}'
            P[pid], where[pid] = ph, sec
    return P, where


def validate(draft, out, T, P, where):
    """문장 단위 검사. 문제가 없으면 None, 있으면 이유 문자열"""
    if not isinstance(out, dict) or list(out) != list(draft):
        return '항목 이름이나 순서가 초안과 다릅니다'
    course_names = {v[1] for k, v in T.items() if re.fullmatch(r'C\d+', k)}
    fact_text_all = ' '.join(str(v[1]) for v in T.values())
    used_p = {}
    for sec, items in out.items():
        if not isinstance(items, list) or not items:
            return f"'{sec}' 항목이 비어 있습니다"
        only_ph = not PH_RE.sub('', draft[sec]).strip()
        n_real = sum(1 for it in items if isinstance(it, dict) and not PH_RE.fullmatch(str(it.get('s', '')).strip()))
        if not only_ph and not (1 <= n_real <= 8):
            return f"'{sec}' 항목의 문장 수가 {n_real}개입니다(1~8개)"
        if sum(len(str(it.get('s', ''))) for it in items if isinstance(it, dict)) > 800:
            return f"'{sec}' 항목이 800자를 넘습니다"
        n_link = 0
        for it in items:
            if not isinstance(it, dict) or not isinstance(it.get('s'), str) or not isinstance(it.get('src'), list):
                return f"'{sec}' 항목의 형식이 잘못됐습니다"
            s, src = it['s'].strip(), [str(x) for x in it['src']]
            if not src:
                return f"근거 없는 문장: {s[:30]}"
            pids = [x for x in src if x in P]
            if pids:
                if len(src) != 1 or s != P[pids[0]]:
                    return f"빈칸 문장은 원문 그대로 혼자 있어야 합니다: {P[pids[0]]}"
                if where[pids[0]] != sec:
                    return f"빈칸 {P[pids[0]]}의 위치가 바뀌었습니다"
                used_p[pids[0]] = used_p.get(pids[0], 0) + 1
                continue
            if PH_RE.search(s):
                return f"빈칸 표시를 다른 문장에 섞었습니다: {s[:30]}"
            if only_ph:
                return f"'{sec}'은 빈칸만 있어야 하는데 문장이 추가됐습니다: {s[:30]}"
            if src == ['연결']:
                n_link += 1
                if n_link > 2 or len(s) > 50:
                    return f"'{sec}'의 연결 문장이 너무 많거나 깁니다: {s[:30]}"
                cited = ''
            else:
                bad = [x for x in src if x not in T]
                if bad:
                    return f"존재하지 않는 근거 ID: {', '.join(bad)}"
                if '프로젝트 경험' in draft and sec != '프로젝트 경험' and any(re.fullmatch(r'C\d+[TRV]', x) for x in src):
                    return f"프로젝트 내용을 '{sec}'에서 반복했습니다: {s[:30]}"
                cited = ' '.join(f'{T[x][0]} {T[x][1]}' for x in src)
            extra = _tokens(s) - _tokens(cited) - _tokens(' '.join(c for c in course_names if c))
            if extra:
                return f"근거에 없는 숫자·영문({', '.join(sorted(extra)[:4])}): {s[:30]}"
            for c in re.findall(r'「([^」]+)」', s):
                if c not in course_names:
                    return f"입력하지 않은 과목명: {c}"
            for w in BANNED:
                if w in s and w not in fact_text_all:
                    return f"과장 표현 '{w}': {s[:30]}"
    missing = [P[p] for p in P if used_p.get(p) != 1]
    if missing:
        return f"빈칸이 빠지거나 중복됐습니다: {missing[0]}"
    return None


def render(out):
    return {sec: ' '.join(it['s'].strip() for it in items) for sec, items in out.items()}


def call(messages, cfg, timeout=40):
    body = {'model': cfg['model'], 'temperature': 0.2, 'messages': messages,
            'response_format': {'type': 'json_object'}}
    if 'gpt-oss' in cfg['model']:
        body['reasoning_effort'] = 'low'          # 추론 토큰 절약 (Groq 무료 한도: 분당 8,000토큰)
    req = urllib.request.Request(cfg['base'] + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': f"Bearer {cfg['key']}", 'Content-Type': 'application/json',
                                          'User-Agent': 'tantandaero/1.0'})   # 기본 Python UA는 Cloudflare 1010으로 차단됨
    last = None
    for attempt in range(2):                      # 429·5xx 한 번 재시도
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            return res['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read()[:200].decode("utf-8", "ignore")}'
            if e.code in (429, 500, 502, 503) and attempt == 0:
                wait = e.headers.get('retry-after') if e.headers else None
                try:
                    wait = float(wait)
                except (TypeError, ValueError):
                    wait = 3
                if wait <= 20:                    # 너무 오래 기다려야 하면 바로 템플릿으로
                    time.sleep(wait)
                    continue
            break
            break
        except Exception as e:                    # 타임아웃·네트워크
            last = str(e)[:200]
            break
    raise RuntimeError(last)


def parse_json(text):
    text = text.strip()
    m = re.search(r'\{.*\}', text, re.S)          # ```json 감싸기 대응
    return json.loads(m.group(0) if m else text)


def polish(draft, facts, max_tries=2):
    """draft: 템플릿 초안 {항목: 본문}, facts: 사용자가 입력한 사실(dict)
    반환: (최종 초안, info{used, provider, model, reason, tries, evidence, labels})"""
    cfg = config()
    info = {'used': False, 'provider': cfg['provider'], 'model': cfg['model'], 'reason': None, 'tries': 0}
    if not (cfg['key'] and cfg['base'] and cfg['model']):
        info['reason'] = 'LLM 키가 설정되지 않아 템플릿 초안을 사용'
        return draft, info
    T = fact_table(facts)
    P, where = placeholder_table(draft)
    table = '\n'.join(f'{k}: {v[0]} = {v[1]}' for k, v in T.items())
    blanks = '\n'.join(f'{k} ({where[k]}): {v}' for k, v in P.items()) or '(없음)'
    user = (f"[사실표]\n{table}\n\n[빈칸표]\n{blanks}\n\n[초안] (이 내용과 순서를 바탕으로 다듬을 것)\n"
            + json.dumps(draft, ensure_ascii=False))
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
    reason = None
    for attempt in range(max_tries):
        info['tries'] = attempt + 1
        try:
            raw = call(msgs, cfg)
            out = parse_json(raw)
        except Exception as e:
            reason = f'LLM 호출 실패 ({e})'
            break
        reason = validate(draft, out, T, P, where)
        if not reason:
            labels = {**{k: v[0] for k, v in T.items()}, **{k: '빈칸' for k in P}, '연결': '연결 문장'}
            info.update(used=True, reason=None, labels=labels,
                        evidence={sec: [{'s': it['s'], 'src': it['src']} for it in items] for sec, items in out.items()})
            return render(out), info
        msgs += [{'role': 'assistant', 'content': raw},
                 {'role': 'user', 'content': f'규칙 위반: {reason}. 이 문제를 고쳐 같은 JSON 형식으로 전체를 다시 작성해.'}]
    info['reason'] = f'{reason} → 템플릿 초안 사용'
    return draft, info
