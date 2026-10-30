# 탄탄대로 – 충북대 수강 이력 기반 채용 매칭·근거형 지원서 AI (캡스톤 MVP)

충북대 학생이 **들은 과목(최대 10개)**과 자격증으로 전국 채용공고를 매칭하고, 그 과목을 근거로 지원서 초안을 만드는 웹 서비스입니다.

## 로컬 실행
```bash
pip install -r requirements.txt
cp .env.example .env     # LLM_API_KEY 입력 (없어도 템플릿 초안으로 동작)
python app.py            # http://localhost:5000
pip install -r requirements-dev.txt && python -m pytest -q   # 테스트 13개, LLM·네트워크 불필요
```

## LLM 연결 (지원서 문장 다듬기)
OpenAI 호환 API 하나로 Gemini · Groq · OpenAI를 모두 씁니다. `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`만 바꾸면 됩니다.

| 공급자 | LLM_PROVIDER | 기본 LLM_MODEL |
|---|---|---|
| Google Gemini | gemini | gemini-flash-latest |
| Groq | groq | openai/gpt-oss-120b (2026-10 기준 확인) |
| OpenAI | openai | gpt-4o-mini |
| 기타 호환 API | custom (+ LLM_BASE_URL) | 직접 지정 |

LLM 결과는 그대로 쓰지 않고 검사합니다. ① `[직접 입력]` 표시가 사라지거나 ② 입력에 없던 숫자·영문 도구명이 생기거나 ③ 항목 구성이 바뀌면 거부하고 템플릿 초안을 씁니다. 화면에 사용 여부와 이유가 표시됩니다. `/api/health`에서 연결 상태를 확인할 수 있고, 키 값은 노출되지 않습니다.

## 과목 학습 주제 (강의계획서 대체)
- `course_syllabus` 테이블: 과목 1,114개의 학습 주제 4~6개와 개요. 출처는 `추정(강의명 기반)`이며, 과목명·학과로 일반적인 강의계획서 내용을 LLM이 추정한 값입니다.
- 실제 강의계획서를 확보하면 같은 테이블에 `출처='강의계획서'`로 넣으면 추정값을 대체합니다(`pipeline/gen_syllabus.py`).
- 화면에서 학생이 배우지 않은 주제를 끌 수 있고, 초안은 남긴 주제만 "학습했습니다" 수준으로 씁니다. 표에 없는 과목은 LLM 키가 있으면 즉석에서 추정합니다.

## 배포
- **Render (추천)**: GitHub 저장소 연결 → `render.yaml` 자동 인식 → 대시보드에서 `LLM_API_KEY` 입력. 무료 플랜은 15분 미사용 시 잠들어 첫 접속이 느립니다.
- **Vercel**: `vercel.json` + `api/index.py` 포함. 저장소를 Import하고 Environment Variables에 `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL` 입력.
- DB(SQLite)는 읽기 전용으로만 쓰므로 두 곳 모두 그대로 동작합니다. 사용자 입력은 브라우저에만 저장됩니다.

## 화면 흐름
1. 내 정보: 관심 직렬(최대 2개) → 직무 키워드, 학력, 자격증, 희망 지역
2. 대표 과목: 과목 검색 후 최대 10개 선택
3. 공고 매칭: 적합도(0~100)와 근거(어떤 과목이 어떤 키워드에 맞는지), 부족한 키워드, 지원 불가 사유
4. 지원서: 공고에 쓸 과목(최대 3개)과 고른 이유(성적·성과물·직무지식) 입력 → 초안 → Word 저장

## 적합도 점수 (규칙 기반)
| 항목 | 배점 | 기준 |
|---|---|---|
| 직무 적합 | 55 | 공고 직무 키워드를 내 과목·관심 직무가 덮는 정도 (과목 주 키워드 2, 부 1, 관심 2 / 키워드당 4면 충족) |
| 직렬 일치 | 10 | 공고 주 키워드가 내가 고른 직렬에 속함 |
| 자격증 | 15 | 공고에 적힌 자격증 보유 15, 해당 직무 대표 자격증 보유 8 |
| 학력 | 10 | 지원 가능 시 |
| 지역 | 10 | 희망 지역 일치 또는 미지정 |

지원 불가: 학력 미달, 필수 자격증(운전면허 제외) 미보유, 마감 지남.

## 폴더
- `app.py` Flask API · `matcher.py` 매칭 · `draft.py` 지원서·Word · `static/index.html` 화면
- `data/cbnu.sqlite` 교과목 3,881개, 직렬 12개·직무 키워드 112개, 고용24 공고 656건(2026-10-28·30 수집)
- 2차 확장(10/30): 이차전지·에너지·화학, 바이오·제약·식품, 기계·자동차·로봇, 건설·환경·안전, 공공·행정·교육·복지, 디자인·미디어·콘텐츠, 금융·보험 추가.
  과목·공고 매핑은 `pipeline/map_llm.py`(LLM 초안) → `merge_course_map.py`/`merge_posting_map.py` → `map/m05.txt`, `postmap/p04.txt` (검수 대상)
- `pipeline/` 데이터 생성 스크립트와 매핑 원본(`map/` 과목→키워드, `postmap/` 공고→키워드)
