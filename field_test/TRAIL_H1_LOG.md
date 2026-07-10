# TRAIL H1 실측 로그

**파일:** `field_test/trail_sample.json` (PatronusAI/TRAIL GAIA/0140b3f657eddf76ca82f72c49ac8e58.json)
**실행일:** 2026-07-10
**커맨드:** `python -m clew analyze field_test/trail_sample.json --no-snippets`
**파라미터:** φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2

---

## 파서 처리 결과

- 전체 스팬: 60개 (Patronus 래퍼 4개 + OI 스팬 56개)
- output.value 없어 건너뜀: 12개 (Step 4, PageDownTool×5, Step 5~8, Step 13, FinalAnswerTool)
- 유효 OI 스팬: 44개
- dangling 루트: 8개 → synthetic CHAIN 루트 삽입 (CodeAgent.run + LiteLLMModel.__call__ ×7)
- 최종 Trace 스팬 수: 45개 (synthetic root 포함)

---

## FIRE 결과

**건수: 1건**

| 항목 | 값 |
|------|-----|
| pattern | repeat_node |
| cosine | 0.6141 |
| 추정 낭비 토큰 | 3,753 |
| 추정 낭비 비용 | unknown (o3-mini 단가 미등록) |

---

## FIRE 상세

### Origin span
- **span_id:** `73d0ef3c402d7d0b`
- **name:** `Step 1` (CodeAgent.run 소속)
- **kind:** chain

**input_text (앞 300자):**
```
{"memory_step": "ActionStep(model_input_messages=None, tool_calls=None, start_time=1742402889.6344829, end_time=None, step_number=1, error=None, duration=None, model_output_message=None, model_output=
```

**output_text (앞 500자):**
```
Execution logs:
Last output from code snippet:
Here is the final answer from your managed agent 'search_agent':
### 1. Task outcome (short version):
The equine veterinarian's surname is Louvrier.

### 2. Task outcome (extremely detailed version):
During our search of the LibreText Introductory Chemistry materials (specifically the '1.E Exercises' section), we navigated to the page at https://chem.libretexts.org/... which is a page of exercises from the LibreTexts materials. Although the page's m
```

---

### Candidate (repeat) span
- **span_id:** `cecfea320b4aa63a`
- **name:** `Step 1` (ToolCallingAgent.run 소속)
- **kind:** chain

**input_text (앞 300자):**
```
{"memory_step": "ActionStep(model_input_messages=None, tool_calls=None, start_time=1742402929.155099, end_time=None, step_number=1, error=None, duration=None, model_output_message=None, model_output=N
```

**output_text (앞 500자):**
```
Address: google: LibreText Introductory Chemistry materials compiled 08/21/2023 CK-12 license Marisa Alviar-Agnew & Henry Agnew '1.E Exercises' equine veterinarian
Title: LibreText Introductory Chemistry materials compiled 08/21/2023 CK-12 license Marisa Alviar-Agnew & Henry Agnew '1.E Exercises' equine veterinarian - Search
Viewport position: Showing page 1 of 1.
=======================
A Google search for 'LibreText Introductory Chemistry materials compiled 08/21/2023 CK-12 license Marisa Alvi
```

---

## 관찰 (사실만)

- **공통점:** 두 스팬 모두 LibreText / equine veterinarian(수의사 Louvrier) / 1.E Exercises 동일 주제를 다룸.
- **차이점:** origin은 managed search_agent가 정리한 최종 답변 서술; candidate는 동일 주제를 구글 검색한 원시 결과 페이지(URL·title·viewport 텍스트). 역할이 다름에도 코사인 0.61 — 주제 중첩이 유사도를 끌어올림.
- **비낭비 쌍:** 1쌍, cosine=0.2805, φ(0.514345) 초과 0/1.
- FIRE 판정 정확도 산출은 이 로그에서 하지 않음 (사전등록 기준: 외부 라벨 3~5건 수집 후 별도 실험).
