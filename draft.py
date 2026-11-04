"""지원서 초안 작성
원칙: 사용자가 입력한 사실만 쓴다. 비어 있는 내용은 [직접 입력: ...]으로 남긴다.
LLM 문장 다듬기는 llm.py가 담당한다(키가 없거나 검증에 실패하면 템플릿 그대로).
"""
import io
import re

from docx import Document
from docx.shared import Pt

REASON_LABEL = {'grade': '높은 성적', 'output': '프로젝트·과제 성과물', 'knowledge': '직무 관련 지식'}


def _jong(word):
    """마지막 글자 받침 여부 (한글이 아니면 받침 없음으로 처리)"""
    w = re.sub(r'[\s\]\)」』\'"]+$', '', str(word))
    if not w:
        return False, False
    c = ord(w[-1])
    if 0xAC00 <= c <= 0xD7A3:
        j = (c - 0xAC00) % 28
        return j != 0, j == 8          # 받침 있음, ㄹ받침
    return False, False


def j(word, pair):
    """조사 붙이기: j('과목', '을를') → '과목을'"""
    has, rieul = _jong(word)
    if pair == '으로':
        return word + ('로' if (not has or rieul) else '으로')
    return word + (pair[0] if has else pair[1])


def clean_title(t):
    t2 = re.sub(r'^(\s*[\[【(][^\]】)]*[\]】)]\s*)+', '', t).strip() or t
    return t2.rstrip(' .!~')


def ends_sentence(t):
    return bool(t) and (t[-1] in '.!?' or t.endswith(('다', '요')))


def finish(t, kind):
    """사용자가 명사형·연결형으로 적은 입력을 완결된 문장으로 감싼다 (내용은 바꾸지 않음)"""
    t = (t or '').strip().rstrip('.')
    if not t:
        return ''
    if ends_sentence(t):
        return t if t[-1] in '.!?' else t + '.'
    if kind == 'motive':
        return f"{t} 지원했습니다." if t.endswith(('서', '고', '며')) else f"'{t}'라는 이유로 지원했습니다."
    if kind == 'goal':
        josa = '이' if _jong(t)[0] else '가'
        return f"'{t}'{josa} 제 목표입니다."
    if kind == 'result':
        return f"그 결과 '{t}'라는 성과를 확인했습니다."
    return t + '.'


def sent(t):
    """사용자 입력 문장 끝에 마침표 보정"""
    t = (t or '').strip()
    return t if not t or t[-1] in '.!?다요' else t + '.'


def ph(what):
    return f'[직접 입력: {what}]'


def join_names(names):
    qs = [f'「{n}」' for n in names]
    if not qs:
        return ''
    if len(qs) == 1:
        return qs[0]
    return ', '.join(qs[:-2] + [j(qs[-2], '과와')]) + ' ' + qs[-1]


def list_ko(items, n=3):
    items = [x for x in items if x][:n]
    if not items:
        return ''
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' 및 ' + items[-1]


def knowledge_sentence(name, r):
    """직무 역량: 학습 주제(강의계획서/추정) + 배운 내용 + 성적 (입력·선택한 것만)"""
    reasons, q = r.get('reasons', []), f'「{name}」'
    topics = r.get('topics') or []
    parts = []
    if topics:
        parts.append(f"{q}에서는 {j(list_ko(topics, 4), '을를')} 학습했습니다.")
    if 'knowledge' in reasons and r.get('learned'):
        parts.append(f"특히 {j(r['learned'], '을를')} 깊이 있게 익혀 직무 이해의 바탕을 다졌습니다.")
    if 'grade' in reasons and r.get('grade'):
        parts.append(f"이 과목은 {j(r['grade'], '으로')} 이수했습니다.")
    if not parts and not ('output' in reasons and (r.get('title') or r.get('role'))):
        parts.append(f"{q} 과목을 수강하며 관련 지식을 익혔습니다.")
    return ' '.join(parts)


def project_sentence(name, r):
    """프로젝트 경험: 성과물 (비어 있는 칸은 문장에서 뺌)"""
    if 'output' not in r.get('reasons', []) or not (r.get('title') or r.get('role')):
        return ''
    q = f'「{name}」'
    what = f"'{r['title']}' 프로젝트를 진행했습니다" if r.get('title') else '팀 프로젝트를 진행했습니다'
    s = f"{q} 수업에서 {what}."
    if r.get('role'):
        s += f" 이 프로젝트에서 {j(r['role'], '을를')} 맡았습니다."
    if r.get('tools'):
        s += f" 작업에는 {r['tools']} 등을 활용했습니다."
    if r.get('result'):
        s += ' ' + finish(r['result'], 'result')
    return s


# ---------- 공고에서 근거 뽑기 (담당 업무·회사 소개) ----------
_TASK_WORD = re.compile(r'개발|관리|분석|설계|운영|기획|지원|수립|작성|개선|생산|품질|영업|상담|교육|시험|검사|유지보수|구축|'
                        r'연구|측정|점검|정비|시공|마케팅|회계|세무|구매|물류|제작|편집|디자인|번역|심사|조사|평가|협업|대응')
_TASK_NO = re.compile(r'급여|연봉|만원|시급|근무\s*시간|근무일|복지|휴무|휴가|우대|자격|지원\s*방법|접수|담당자|문의|전화|이메일|@|http|'
                      r'제출|서류|면접|채용\s*절차|경험|이해|능력|가능자|소지|역량|필수|모집\s*인원|기숙사|식사|4대보험|퇴직금|상여|인센티브|주\s*\d일|~\s*\d{1,2}:\d{2}')


def job_tasks(text, n=6):
    """공고 직무내용 → 담당 업무 문장 목록 (글머리표 줄·업무 동사가 있는 짧은 줄만)"""
    out = []
    for ln in re.split(r'\n|\s-\s', str(text or '')):
        t = re.sub(r'^[\s\-–·•*▶▷◆◇○●■□※✔✓>①-⑩\d.)]+', '', ln).strip(' .,:;')
        t = re.sub(r'\s+', ' ', t)
        if not (6 <= len(t) <= 60) or _TASK_NO.search(t) or not _TASK_WORD.search(t) or re.search(r'[\[\]!?]', t):
            continue
        if re.search(r'기타\s*업무|그\s*외', t) or t.endswith(('니다', '세요', '며', '고', '는', '을', '를', '분')):
            continue
        if t not in out:
            out.append(t)
    return out[:n]


def company_info(upjong):
    """업종 칸 → (업종명, 주요사업 설명). 공고에 적힌 내용만 사용"""
    u = re.sub(r'\s+', ' ', str(upjong or '')).strip()
    if not u:
        return None, None
    name, _, desc = u.partition('주요사업')
    desc = desc.strip(' -:')
    keep = ''
    for sent in re.split(r'(?<=다\.)\s*', desc):           # 문장 단위로 160자까지
        if sent and len(keep) + len(sent) <= 160:
            keep = (keep + ' ' + sent).strip()
    desc = keep if len(keep) > 10 else None
    return (name.strip(' -') or None), desc


def _overlap(a, b):
    """두 문장의 2글자 조각 겹침 수 (간단한 관련도)"""
    A = {a[i:i + 2] for i in range(len(a) - 1) if ' ' not in a[i:i + 2]}
    B = {b[i:i + 2] for i in range(len(b) - 1) if ' ' not in b[i:i + 2]}
    return len(A & B)


def best_task(tasks, words):
    """과목 주제·이름과 가장 많이 겹치는 공고 업무 (없으면 None)"""
    if not tasks:
        return None
    sc = [(sum(_overlap(t, w) for w in words), t) for t in tasks]
    sc.sort(key=lambda x: -x[0])
    return sc[0][1] if sc[0][0] > 0 else None


LINK = ["이 내용은 공고의 '{t}' 업무를 이해하는 바탕이 됩니다.",
        "이는 공고에 적힌 '{t}' 업무와 맞닿아 있습니다.",
        "공고의 '{t}' 업무에서 이 지식을 활용할 수 있습니다."]


def build_template(post, profile, picked, course_names, reasons, extra=None):
    """과목·성과물 입력과 과목 학습 주제만으로 완성되는 초안 ([직접 입력] 칸 없음)"""
    kw = (post.get('직무키워드') or '').split(',')[0].split(' ', 1)[-1].replace('(부)', '').strip() or '해당 직무'
    certs = ', '.join(profile.get('certs', []))
    names = [course_names[c] for c in picked]
    R = {c: reasons.get(c, {}) for c in picked}
    all_topics = [t for c in picked for t in (R[c].get('topics') or [])[:2]]
    sec = {}
    tasks = post.get('업무') or []
    words = names + all_topics + [t for c in picked for t in (R[c].get('topics') or [])]
    task = best_task(tasks, words)
    s = [f"{post['company']}의 '{clean_title(post['title'])}' 공고를 보고 {kw} 직무에 지원합니다."]
    first = re.split(r'(?<=다\.)\s*', post.get('회사소개') or '')[0]
    if first.endswith('다.') and len(first) <= 90:
        s.append(f"공고 소개에 따르면, {first}")
    if task:
        s.append(f"특히 공고의 '{task}' 업무가 제가 수업에서 공부한 내용과 맞닿아 있어 관심을 갖게 되었습니다.")
    s.append(f"충북대학교에서 {join_names(names)} 등 {kw} 직무와 맞닿은 과목을 수강해 왔습니다.")
    if all_topics:
        s.append(f"수업에서 다룬 {list_ko(all_topics, 3)}은(는) {kw} 업무의 기초가 되는 내용이라고 생각합니다."
                 .replace('은(는)', '은' if _jong(list_ko(all_topics, 3))[0] else '는'))
    s.append(f"이렇게 쌓은 지식을 {post['company']}의 {kw} 업무에서 실제로 활용하고자 지원하게 되었습니다.")
    sec['지원 동기'] = ' '.join(s)
    know, used = [], set()
    for c in picked:                                  # 과목별: 배운 주제 → 맞닿는 공고 업무
        k = knowledge_sentence(course_names[c], R[c])
        if not k:
            continue
        know.append(k)
        t = best_task([x for x in tasks if x not in used], [course_names[c]] + list(R[c].get('topics') or []))
        if t:
            used.add(t)
            know.append(LINK[len(used) % len(LINK)].format(t=t))
    sec['직무 역량'] = ' '.join(know + ([f"또한 {certs} 자격을 취득했습니다."] if certs else [])) or \
        f"{join_names(names)} 과목을 수강하며 {kw} 직무의 기초를 익혔습니다."
    proj = []
    for c in picked:                                  # 성과물별: 무엇을 했는지 → 공고 업무와의 연결
        x = project_sentence(course_names[c], R[c])
        if not x:
            continue
        proj.append(x)
        t = best_task(tasks, [R[c].get('title') or '', R[c].get('role') or '', R[c].get('tools') or ''])
        if t:
            proj.append(f"이 경험은 공고의 '{t}' 업무와 직접 이어집니다.")
    if proj:
        sec['프로젝트 경험'] = ' '.join(proj)
    tools = [R[c].get('tools') for c in picked if R[c].get('tools')]
    p = [f"입사 후에는 {join_names(names)}에서 익힌 내용을 {kw} 실무에 적용하겠습니다."]
    if task:
        p.append(f"먼저 '{task}' 업무를 정확히 익혀, 수업에서 배운 내용을 실제 업무 방식에 맞게 연결하겠습니다.")
    if all_topics:
        p.append(f"특히 {j(list_ko(all_topics, 2), '을를')} 실제 업무 상황에 맞게 다시 익히며 현장 이해를 넓히겠습니다.")
    if tools:
        p.append(f"수업에서 다뤄 본 {', '.join(tools)} 활용 경험도 업무에 살리겠습니다.")
    p.append("맡은 업무를 빠르게 익히고 꾸준히 배우며 성장하는 구성원이 되겠습니다.")
    sec['입사 후 포부'] = ' '.join(p)
    return sec


def to_docx(title, sections):
    doc = Document()
    st = doc.styles['Normal']
    st.font.name = 'Malgun Gothic'
    st.font.size = Pt(10.5)
    doc.add_heading(title, level=1)
    for h, body in sections.items():
        doc.add_heading(h, level=2)
        for para in str(body).split('\n'):
            doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
