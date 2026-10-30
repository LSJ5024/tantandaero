"""고용24 채용정보 시연용 스냅샷 수집 (공개 검색 페이지, robots.txt 허용 경로 /wk/)
- 요청 간격 2초, 소량 수집
- 담당자 이름·연락처 등 개인정보는 저장하지 않음
출력: w24/list.json, w24/postings.json
"""
import json, re, sys, time, html, urllib.parse, urllib.request
from datetime import datetime

OUT = sys.argv[1]
UA = {'User-Agent': 'Mozilla/5.0 (CBNU capstone demo; low-rate)'}
LIST = 'https://www.work24.go.kr/wk/a/b/1200/retriveDtlEmpSrchList.do'
DELAY = 2.0

QUERIES = {
    'T1 경영·사무': ['회계', '재무', '세무', '마케팅', '영업관리', '인사', '총무', '해외영업', '무역', '경영지원', '경영기획'],
    'T2 생산·품질·SCM': ['생산관리', '품질관리', '구매', '물류', 'SCM', '자재관리', 'ERP'],
    'T3 SW·데이터': ['개발자', '백엔드', '프론트엔드', '데이터 분석', '정보보안', '인공지능', '전산', '웹개발'],
    'T4 반도체 공정·소재': ['반도체 공정', '공정엔지니어', '화학공정', '화학 연구원', '분석 연구원', '이차전지', '환경안전', '소재 개발'],
    'T5 전자·반도체 설계·설비': ['회로설계', '반도체 장비', '설비 엔지니어', '임베디드', '펌웨어', '전기설계', '제어', '하드웨어'],
    # ── 2차 확장 (2026-10-30) ──
    'T6 이차전지·에너지·화학': ['배터리', '이차전지 공정', '양극재', '화학공장', '화학 생산관리', '신재생에너지', '전기안전관리', '공정안전'],
    'T7 바이오·제약·식품': ['제약 생산', 'GMP', '의약품 품질', 'QC 연구원', '바이오 연구원', '식품 품질관리', '식품 연구원', '화장품 연구원', '의료기기'],
    'T8 기계·자동차·로봇': ['기계설계', '생산기술', '설비보전', '자동화 설비', 'PLC', '자동차 부품', '로봇', 'CAE', '금형'],
    'T9 건설·환경·안전': ['건축설계', '건축 현장관리', '토목', '도시계획', '공무', '환경 측정', '수처리', '산업안전', '소방', '측량'],
    'T10 공공·행정·교육·복지': ['행정사무', '공공기관', '연구원 행정', '교육 강사', '교육 운영', '사회복지사', '청소년지도사', '상담사', '평생교육'],
    'T11 디자인·미디어·콘텐츠': ['UI 디자이너', '웹디자이너', '시각디자인', '편집디자인', '영상편집', '콘텐츠 마케팅', '홍보', '기자', '번역', '출판 편집'],
    'T12 금융·보험': ['은행', '대출 심사', '증권', '자산관리', '보험 영업관리', '손해사정', '리스크관리', '금융 IT'],
}


def get(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=UA)
    for i in range(3):
        try:
            return urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'ignore')
        except Exception as e:
            time.sleep(5)
    return ''


def search(q, cnt=50):
    p = {'srcKeyword': q, 'keyword': q, 'careerTypes': 'N,Z', 'academicGbn': '00,04,05',
         'resultCnt': cnt, 'currentPageNo': 1, 'pageIndex': 1, 'sortField': 'DATE', 'sortOrderBy': 'DESC'}
    t = get(LIST, p)
    out = []
    for tr in re.findall(r'<tr id="list\d+">(.*?)</tr>', t, re.S):
        v = re.search(r'value="([^"|]+)\|([^"|]*)\|([^"|]*)\|([^"]*)"', tr)
        href = re.search(r'href="(/wk/a/b/1500/empDetailAuthView\.do\?[^"]+)"', tr)
        tags = re.findall(r'class="tbl_label[^"]*">([^<]+)<', tr)
        if v and href:
            out.append({'id': v.group(1), 'company': html.unescape(v.group(3)), 'title': html.unescape(v.group(4)),
                        'url': 'https://www.work24.go.kr' + html.unescape(href.group(1)),
                        'labels': [x.strip() for x in tags if x.strip()]})
    return out


FIELDS = ['경력', '학력', '임금 조건', '근무 예정지', '고용 형태', '모집 직종', '관련 직종', '직종 키워드', '자격 면허',
          '모집 인원', '전공', '컴퓨터 활용 능력', '외국어 능력', '우대조건', '기타 우대사항', '접수 마감일',
          '채용공고 등록일시', '업종', '기업규모', '근로자수', '설립연도']


def detail(url):
    t = get(url)
    t = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S)
    x = html.unescape(re.sub(r'<[^>]+>', '\n', t))
    x = re.sub(r'[ \t]+', ' ', x)
    lines = [l.strip() for l in x.split('\n') if l.strip()]
    d = {}
    for i, l in enumerate(lines):
        if l in FIELDS and l not in d and i + 1 < len(lines):
            vals = []
            for nx in lines[i + 1:i + 5]:          # 다음 필드명이 나오기 전까지 최대 4줄
                if nx in FIELDS or nx in ('근무조건', '우대사항', '기타사항', '복리후생'): break
                vals.append(nx)
            d[l] = ' '.join(vals)
    # 모집요강 본문 ~ 채용 담당자 직전까지 원문 보관 (담당자 개인정보 제외)
    try:
        a = lines.index('모집요강', lines.index('모집요강') + 1); b = lines.index('채용 담당자')
        d['_raw'] = '\n'.join(lines[a:b])[:6000]
    except ValueError:
        d['_raw'] = ''
    # 직무내용: '직무내용' ~ '더보기' 사이
    try:
        a = lines.index('직무내용'); b = lines.index('더보기', a)
        d['직무내용'] = '\n'.join(lines[a + 1:b])[:3000]
    except ValueError:
        d['직무내용'] = ''
    return d


if __name__ == '__main__':
    stage = sys.argv[2]
    if stage == 'list':
        only = sys.argv[3].split(',') if len(sys.argv) > 3 else None     # 예: T6,T7 (해당 직렬만 수집)
        seen, rows = set(), []
        for track, qs in QUERIES.items():
            if only and track.split(' ')[0] not in only:
                continue
            for q in qs:
                r = search(q)
                n = 0
                for x in r:
                    if x['id'] in seen: continue
                    seen.add(x['id']); x['track_query'] = track; x['query'] = q; rows.append(x); n += 1
                print(track, q, len(r), 'new', n, flush=True)
                time.sleep(DELAY)
        json.dump(rows, open(OUT + '/list.json', 'w'), ensure_ascii=False, indent=1)
        print('total', len(rows))
    else:
        ids = set(json.load(open(OUT + '/select.json')))
        rows = [r for r in json.load(open(OUT + '/list.json')) if r['id'] in ids]
        done = {}
        try: done = {p['id']: p for p in json.load(open(OUT + '/postings.json'))}
        except Exception: pass
        for i, r in enumerate(rows):
            if r['id'] in done: continue
            d = detail(r['url'])
            r.update({'detail': d, 'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M')})
            done[r['id']] = r
            if i % 10 == 0:
                json.dump(list(done.values()), open(OUT + '/postings.json', 'w'), ensure_ascii=False, indent=1)
                print(i, len(rows), flush=True)
            time.sleep(DELAY)
        json.dump(list(done.values()), open(OUT + '/postings.json', 'w'), ensure_ascii=False, indent=1)
        print('done', len(done))
