# REQUERY_DIAGNOSIS — requery 오탐 진단 (Stage 18)

**실행일:** 2026-07-12  
**파라미터:** φ=0.514345, N=2, model=paraphrase-multilingual-MiniLM-L12-v2  
**트레이스 수:** 80개  **requery FIRE 총수:** 8건  
**필터:** tool kind + 입력 정규화 동일 (structural 레이어 보장)  
**_extract_target:** TRAIL 전용 참고용 — 판정·집계에 불사용

---

## 데이터 한계 (판정 전 기록)

- 사전등록 목표(SPEC §18): requery FIRE 10건+
- 실측: 8건 — 목표 미달
- 미달 사유: TRAIL 데이터 소스 고갈
  - 전체 147개 파일 중 크기 상위 80개 처리 완료
  - 미사용 67개는 전부 소형(최대 318 KB), requery FIRE 발생 최소 기준선(2,903 KB)의 1/10 이하
  - 기준선 이상 미사용 트레이스: 0개 (메타데이터 확인 근거)
  - 100개 확장해도 FIRE 추가 가능성 없음
- 결과: 이 8건은 stage17과 동일 집합. 이번 진단의 신규 가치는 (a) 원문 800자 전문 정밀 판정, (b) origin 선택 관찰 항목.
- 결론 강등 규칙: 교차표에서 상관이 나와도 "예비 신호"로만 취급. stage19 게이트를 설계하더라도 최종 검증은 실제 워크로드(KAIST 경로) 트레이스에서 수행. TRAIL 8건으로 게이트 검증까지 닫으면 오버핏.

---

## requery FIRE 상세

### REQUERY #1 — G3/GAIA/915d2c66879657f694f88e0ed6f02cf5.json
- cosine: 0.8062  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `9934740a5367903e`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/9533
Viewport position: Showing page 1 of 59.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/9533`

**Candidate** `ae0a863d3e610906`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/9533/events
Title: Error 404
Viewport position: Showing page 1 of 1.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/9533/events`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [X] 해당없음
- 메모: 

---

### REQUERY #2 — G3/GAIA/915d2c66879657f694f88e0ed6f02cf5.json
- cosine: 0.9757  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `9934740a5367903e`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/9533
Viewport position: Showing page 1 of 59.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/9533`

**Candidate** `956ef04f5ca0e457`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/22104
Viewport position: Showing page 1 of 50.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/22104`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [X] 해당  [ ] 해당없음
- 메모: candidate는 22104인데 origin은 9533으로 고정.

---

### REQUERY #3 — G3/GAIA/915d2c66879657f694f88e0ed6f02cf5.json
- cosine: 0.9744  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `9934740a5367903e`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/9533
Viewport position: Showing page 1 of 59.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/9533`

**Candidate** `f05d0c56d33a586d`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/22104
Viewport position: Showing page 1 of 50.
=======================
The search string 'regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/22104`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [X] 해당  [ ] 해당없음
- 메모: candidate는 22104인데 origin은 9533으로 고정.

---

### REQUERY #4 — G3/GAIA/915d2c66879657f694f88e0ed6f02cf5.json
- cosine: 0.9757  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `9934740a5367903e`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/9533
Viewport position: Showing page 1 of 59.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/9533`

**Candidate** `ea3d20ceb3e1577c`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Regression"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "regression"}}`
- output (전문, 최대 800자):
```
Address: https://github.com/numpy/numpy/issues/22104
Viewport position: Showing page 1 of 50.
=======================
The search string 'Regression' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://github.com/numpy/numpy/issues/22104`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [X] 해당  [ ] 해당없음
- 메모: candidate는 22104인데 origin은 9533으로 고정.

---

### REQUERY #5 — G8/GAIA/f84e4dfe98f92d8d39a1e00115cd77df.json
- cosine: 0.9639  tool: VisitTool  부모AGENT: ToolCallingAgent.run

**Origin** `d134f60601a2b24f`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"url": "https://en.wikipedia.org/wiki/Untitled_Goose_Game"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"url": "https://en.wikipedia.org/wiki/untitled_goose_game"}}`
- output (전문, 최대 800자):
```
Address: https://en.wikipedia.org/wiki/Untitled_Goose_Game
Viewport position: Showing page 1 of 53.
=======================
<!DOCTYPE html>
<html class="client-nojs vector-feature-language-in-header-enabled vector-feature-language-in-main-page-header-disabled vector-feature-page-tools-pinned-disabled vector-feature-toc-pinned-clientpref-1 vector-feature-main-menu-pinned-disabled vector-feature-limited-width-clientpref-1 vector-feature-limited-width-content-enabled vector-feature-custom-font-size-clientpref-1 vector-feature-appearance-pinned-clientpref-1 vector-feature-night-mode-enabled skin-theme-clientpref-day vector-sticky-header-enabled vector-toc-available" lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<title>Untitled Goose Game - Wikipedia</title>
<script>(function(){var classNa
```
- 참고(자동추출, TRAIL 전용): `https://en.wikipedia.org/wiki/Untitled_Goose_Game`

**Candidate** `92b967fa013b01c1`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"url": "https://en.wikipedia.org/wiki/Untitled_Goose_Game"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"url": "https://en.wikipedia.org/wiki/untitled_goose_game"}}`
- output (전문, 최대 800자):
```
Address: https://en.wikipedia.org/wiki/Untitled_Goose_Game
You previously visited this page 46 seconds ago.
Viewport position: Showing page 1 of 53.
=======================
<!DOCTYPE html>
<html class="client-nojs vector-feature-language-in-header-enabled vector-feature-language-in-main-page-header-disabled vector-feature-page-tools-pinned-disabled vector-feature-toc-pinned-clientpref-1 vector-feature-main-menu-pinned-disabled vector-feature-limited-width-clientpref-1 vector-feature-limited-width-content-enabled vector-feature-custom-font-size-clientpref-1 vector-feature-appearance-pinned-clientpref-1 vector-feature-night-mode-enabled skin-theme-clientpref-day vector-sticky-header-enabled vector-toc-available" lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<title>Untitled Goose Game - 
```
- 참고(자동추출, TRAIL 전용): `https://en.wikipedia.org/wiki/Untitled_Goose_Game`

**판정 (전세원 확정):**
- 대상: [X] 같은대상  [ ] 다른대상  [ ] 애매
- 낭비: [X] 진짜낭비  [ ] 정당한탐색  [ ] 애매
- 메모: 도구가 "previously visited 46 seconds ago" 직접 명시.

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [X] 해당없음
- 메모: 

---

### REQUERY #6 — G8/GAIA/f84e4dfe98f92d8d39a1e00115cd77df.json
- cosine: 0.7138  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `7b77785f1cc9259b`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Released"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "released"}}`
- output (전문, 최대 800자):
```
Address: https://en.wikipedia.org/w/index.php?title=Untitled_Goose_Game&action=history
Viewport position: Showing page 20 of 41.
=======================
type="radio" value="1273674441" name="diff" id="mw-diff-1273674441"> <bdi dir="ltr"><span class="mw-changeslist-time">13:13</span><bdi dir="ltr"><a href="/w/index.php?title=Untitled_Goose_Game&amp;oldid=1273674441" class="mw-changeslist-date" title="Untitled Goose Game">13:13, 3 February 2025</a></bdi></bdi> <span class='history-user'><a href="/wiki/User:Popcornfud" class="mw-userlink" title="User:Popcornfud" data-mw-revid="1273674441"><bdi>Popcornfud</bdi></a> <span class="mw-usertoollinks mw-changeslist-links"><span><a href="/wiki/User_talk:Popcornfud" class="mw-usertoollinks-talk" title="User talk:Popcornfud">talk</a></span> <span><a hr
```
- 참고(자동추출, TRAIL 전용): `https://en.wikipedia.org/w/index.php?title=Untitled_Goose_Game&action=history`

**Candidate** `c8fe748aa4358f96`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "Released"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "released"}}`
- output (전문, 최대 800자):
```
Address: https://en.wikipedia.org/wiki/Untitled_Goose_Game
You previously visited this page 51 seconds ago.
Viewport position: Showing page 11 of 53.
=======================
ol li,.mw-parser-output .plainlist ul li{margin-bottom:0}</style><div class="plainlist"><ul><li>Stuart Gillespie-Cook</li><li>Nico Disseldorp</li><li>Michael McMaster</li><li>Jacob Strasser</li></ul></div></td></tr><tr><th scope="row" class="infobox-label"><a href="/wiki/Video_game_composer" class="mw-redirect" title="Video game composer">Composer(s)</a></th><td class="infobox-data"><a href="/wiki/Dan_Golding" title="Dan Golding">Dan Golding</a></td></tr><tr><th scope="row" class="infobox-label"><a href="/wiki/Game_engine" title="Game engine">Engine</a></th><td class="infobox-data"><a href="/wiki/Unity_(game_engine)" t
```
- 참고(자동추출, TRAIL 전용): `https://en.wikipedia.org/wiki/Untitled_Goose_Game`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [ ] 다른대상  [X] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 같은 문서 다른 뷰 — history 20/41 vs 본문 11/53.

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [X] 해당없음
- 메모: 

---

### REQUERY #7 — G10/GAIA/dcb89b6b049d424caf4c3e5fcd22c84c.json
- cosine: 0.6672  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `f47482866538ad6f`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "BB</th>"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "bb</th>"}}`
- output (전문, 최대 800자):
```
Address: http://web.archive.org/web/20200401235817/https://www.baseball-reference.com/teams/NYY/1977.shtml
Viewport position: Showing page 32 of 118.
=======================
class="table_wrapper">

<div class="section_heading">
  <span class="section_anchor" id="team_batting_link" data-label="Team Batting"></span><h2>Team Batting</h2>    <div class="section_heading_text">
      <ul>
	  <li><a href="/web/20200401235817/https://www.baseball-reference.com/leagues/AL/1977-standard-batting.shtml">League Register</a></li>
      </ul>
    </div>

</div>   <div class="table_outer_container">
      <div class="overthrow table_container" id="div_team_batting">

  <table class="sortable stats_table" id="team_batting" data-cols-to-freeze="3" data-non-qual="1" data-qual-text=" (2 PA/TmG)" data-qual-lab
```
- 참고(자동추출, TRAIL 전용): `http://web.archive.org/web/20200401235817/https://www.baseball-reference.com/teams/NYY/1977.shtml`

**Candidate** `154e23e1ecb12c60`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "BB</th>"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "bb</th>"}}`
- output (전문, 최대 800자):
```
Address: google: 1977 Yankees BB leader at bats site:baseball-reference.com
Title: 1977 Yankees BB leader at bats site:baseball-reference.com - Search
Viewport position: Showing page 1 of 1.
=======================
The search string 'BB</th>' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `google: 1977 Yankees BB leader at bats site:baseball-reference.com`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [X] 해당없음
- 메모: 

---

### REQUERY #8 — G12/GAIA/c60ad8608dd94271a6c6805eedfa26a8.json
- cosine: 0.6535  tool: FinderTool  부모AGENT: ToolCallingAgent.run

**Origin** `b20ae2596a49c742`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "predicted"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "predicted"}}`
- output (전문, 최대 800자):
```
Address: https://robertmarks.org/InTheNews/2020Media/200421-Comp_files/aygSMgK3BEM.html
Viewport position: Showing page 1 of 13.
=======================
The search string 'predicted' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://robertmarks.org/InTheNews/2020Media/200421-Comp_files/aygSMgK3BEM.html`

**Candidate** `8ddcfd496f7ae744`
- input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "predicted"}}`
- 정규화 input: `{"args": [], "sanitize_inputs_outputs": true, "kwargs": {"search_string": "predicted"}}`
- output (전문, 최대 800자):
```
Address: https://techtv.mit.edu/videos/10268-the-thinking-machine-1961---mit-centennial-film
Title: OVS | Video Detail
Viewport position: Showing page 1 of 1.
=======================
The search string 'predicted' was not found on this page.
```
- 참고(자동추출, TRAIL 전용): `https://techtv.mit.edu/videos/10268-the-thinking-machine-1961---mit-centennial-film`

**판정 (전세원 확정):**
- 대상: [ ] 같은대상  [X] 다른대상  [ ] 애매
- 낭비: [ ] 진짜낭비  [X] 정당한탐색  [ ] 애매
- 메모: 

**origin 선택 관찰 (전세원 확정):**
- candidate들끼리 대상이 같은데 origin만 다른가? [ ] 해당  [X] 해당없음
- 메모: 

---

## 집계 (사람 판정 후 채움)

**requery FIRE 총수: 8건 (tool+동일input, 게이트 통과)**

### 교차표: 대상 동일성 × 진짜 낭비

|              | 진짜낭비 | 정당한탐색 | 애매 |
|--------------|---------|-----------|-----|
| 같은 대상     | 1 (#5)  |     0     |  0  |
| 다른 대상     |    0    | 6 (#1,2,3,4,7,8) | 0 |
| 애매         |    0    |  1 (#6)   |  0  |

### 확증편향 반례란
- 대상 같은데 정당한탐색: 없음
- 대상 다른데 진짜낭비: 없음

### origin 선택 약점 관찰
- "origin 선택 관찰: 해당" 건수: 3건 (#2, #3, #4)
- 대표 사례(G3 유형 재발 여부): G3 유형 재발. candidate가 전부 issue 22104인데 origin은 9533으로 고정 → "9533 vs 22104" 쌍만 3회 생성. 정작 "22104 3회 방문"이라는 진짜 중복 쌍은 origin 로직이 생성 안 함. stage17에서 지적한 약점 그대로.

### 코사인 분포 관찰
- 대상 동일 군 cosine: 0.9639 (#5, n=1)
- 대상 다른 군 cosine: 0.6535 ~ 0.9757 (#1,2,3,4,7,8)
- 신호 후보: cosine은 신호 아님 (반증됨). 진짜낭비 #5(0.9639)가 정당한탐색 #2/#4(0.9757)보다 낮음 → 분포 겹침. 높은 cosine은 "search string not found" 정형 문구 때문. φ 조정으로 못 가름. → 대상 동일성이 신호.

## 결론 (전세원 확정)

- '대상 동일성이 진짜 낭비를 가르는 신호인가': 유망한 예비 신호. 8건 반례 0. 단 진짜낭비 양성 사례가 n=1(#5)이라 TRAIL만으로 확증 불가. 게다가 #5는 도구가 재방문을 직접 명시한 케이스라, 대상 비교 게이트의 고유 기여는 "오탐 억제"(6건)이지 낭비 신규 탐지가 아님.
- 다음 단계: stage19 requery 게이트 설계 — 목적을 오탐 억제로 명시(낭비 탐지 개선 아님). 대상 식별은 TRAIL "Address:" 정규식이 아닌 일반적 필드로 추상화. 최종 검증은 KAIST 실제 워크로드. TRAIL 8건으로 게이트 검증 닫으면 오버핏.
