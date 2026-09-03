# Changelog

All notable, user-visible changes to `boxdawn` (previously published on PyPI as `clew-custos`). This file tracks releases going forward — earlier versions are not back-filled because the criteria for what qualifies as user-visible were not established at the time.

## 0.5.10 — 2026-09-04 · **Mac 과 Linux 에서는 자동 수집이 아예 없었다**

`boxdawn submit --install` 은 Windows 에서만 실제로 등록됐다. macOS·Linux 에서는
붙여넣을 줄을 출력하고 **0 으로 종료**했다. 감시 사슬이 그 기계에서는 사람이
스케줄러 일을 대신 하지 않으면 시작조차 못 했다.

### 추가 — 세 플랫폼 모두 실제 등록

| 플랫폼 | 등록 | **읽어서 확인** |
|---|---|---|
| Windows | `schtasks /Create /XML` | `schtasks /Query` |
| Linux | `crontab -` (태스크별 펜스 블록) | `crontab -l` |
| macOS | `launchctl load -w` | `launchctl list <label>` |

`schedule.py` 는 오랫동안 그 둘을 거부했고 이유를 스스로 적어뒀다: *이 파일은 그
둘을 테스트할 수 없고, 조용히 실패하는 등록은 없는 것보다 나쁘다.* **위험 진단은
옳았고 처방이 틀렸다.** 처방은 거부가 아니라 **등록한 다음 읽어서 확인하는 것**이다.
확인이 통과할 때만 성공을 보고하고, 실패하면 **예전과 똑같은 안내문**을 준다 —
최악의 경우가 이전 동작과 같으므로 조용한 성공이 도달 불가능하다.

실제 Linux 에서 확인했다(WSL Ubuntu 24.04, 진짜 `crontab`, 29/29): 설치 · 읽기확인 ·
재설치가 교체(중복 아님) · 두 태스크 공존 · uninstall 이 자기 블록만 지움 ·
**사용자가 직접 쓴 crontab 줄이 전 과정에서 보존됨** · 표현 불가능한 간격 거부.

macOS 는 여기 하드웨어가 없다. 명령은 기록된 `launchctl` 동작으로 시험했고, 실제
사용자를 보호하는 것은 읽기확인이다 — 그 macOS 버전에서 명령이 틀리면 **안내문을
받고, 있다고 믿는 에이전트를 받지 않는다.** `RunAtLoad` 는 false 라 에이전트를
올리는 것이 백필 스윕을 발동시키지 않는다.

### 수정 — 두 결함

- **`*/90` 은 "90분마다"가 아니라 cron 이 거부하는 줄이다.** 옛 코드는 어떤 N 에도
  `*/{N}` 을 찍었다. 이제 정시 단위는 시 필드(`0 */2 * * *`)를 쓰고, 표현 불가능한
  간격은 **아무것도 쓰지 않고** 이름을 대며 거부한다.
- 🔴 **`is_registered()` 가 그 두 플랫폼에서 `None` 을 돌려줬고, CLI 는 `None` 을
  "종료코드로 판정하지 말라"로 읽는다.** 그래서 Mac 에서 `--install` 이 **제출
  워터마크를 찍고 0 으로 종료**했다 — 등록된 것이 없는데. 그 워터마크는 이후 백필을
  억제하므로, 사용자가 수집되고 있다고 믿은 구간이 조용히 비었다. 이제 세 플랫폼
  모두 진짜 boolean 을 돌려주고, `None` 은 네 번째 플랫폼을 뜻한다.

### 변경 — 한 탐지기가 두 이름으로 독자에게 닿고 있었다

리포트의 비용 블록은 `provable_duplicate`, 낭비율 줄은 `repeat` 이라 불렀다. 같은
cascade 탐지기다. 한쪽에서 세 줄을 세고 다른 쪽에서 "4 detectors" 를 읽은 독자는
둘을 맞춰볼 방법이 없었다.

```
전:  - provable_duplicate: $0.000000
후:  - repeat: $0.000000
```

**표시 이름만 통일했다. JSON 키는 일부러 그대로다** — `cost_summary.detector_breakdown`
은 웹 앱과 저장 계층의 파싱 계약이고, 라벨을 정리하려고 필드명을 바꾸면 둘 다 깨진다.
그래서 행이 `repeat` 이라 말하고 각주가 키를 밝힌다(그 반대가 아니다).

★ 읽기 문제만이 아니었다: 저장 계층이 한 블록을 다른 블록의 이름으로 읽어
`provable_duplicate.waste_bytes` 가 **2026-08-27 이전에 저장된 모든 행에서 NULL**
이었다(cloud 쪽에서 이미 수정됨, 전방향).

### 변경 — 설치 명령은 `pip install boxdawn` 하나다

`[detect]` extra 가 **패키지 0개**를 해석한다는 것을 깨끗한 venv 두 개로 확인했다
(각 14 패키지 · `pip freeze` diff **0줄**). 그래서 우리가 출력하는 모든 명령에서 뺐다 —
README · CLI 오류문 · CI · ARCHITECTURE. **extra 정의는 남긴다**: 지우면 수개월간
게시된 README·PyPI 페이지·고정된 requirements 를 따라온 사람의 `boxdawn[detect]` 에
pip 이 경고를 띄운다. 빈 채로 두면 그 명령이 조용히 계속 동작한다.

CLI 오류문은 장황한 게 아니라 **틀렸다**: *"detect dependencies missing. Run:
pip install 'boxdawn[detect]'"* 는 그 extra 가 아무것도 설치하지 않으므로 그 실패를
고칠 수 없다. 없는 것은 base 의존성이라 재설치를 안내한다.

### 수정 — README 가 거짓을 두 곳에서 말하고 있었다

`boxdawn submit` 을 *"릴리스에 아직 없다 — 0.5.3 이후 착지"* 라고 적고 있었다.
**0.5.4(2026-08-28)에 출하됐고** 그때부터 모든 릴리스에 있다. 추론이 아니라 실행으로
확인했다: PyPI 0.5.9 을 깨끗한 venv 에 깔고 `boxdawn submit --help` 가 답한다.

### 수정 — 0 인 `waste_cost` 는 float 다

`sum({}.values())` 가 int `0` 을 돌려주므로, 아무것도 플래그하지 않은 탐지기가
`float` 로 선언된 필드로 int 를 돌려줬다. **직렬화 바이트는 무변**이고 추정이 아니라
대조했다 — 제로 트레이스와 1.46MB 실세션 둘 다 byte-identical.
🔴 그 옆 주석이 `union_waste_cost` 도 "같은 흔들림"이 있다고 적고 있었는데 **아니다**:
`span_cost` 가 `0.0` 으로 시작하므로 모든 경로에서 float 다. 이월 항목이 틀린 필드에
적혀 있었다.

### 사용자에게 닿지 않는 것

FM-1.1 결과 문서(제약 18/40 · 위반 0건 — **양성 표본이 비어 축을 세울 수 없었다**)와
FM-2.2 사전등록. 둘 다 문서이며 코드는 없다. FM-2.2 는 축 후보 6개가 연달아 기각된
뒤 **양쪽 모집단을 먼저 세고** 고른 첫 축이다(MAST-Data 265/1,642 · 실제 세션에서
되묻기 144턴 8.10% · 후보 618턴).

1,012 passed / 1 xfailed (`PYTHONPATH=src` 필수).

## 0.5.9 — 2026-09-03 · **판정기가 무엇을 요청받았는지 보지 못하고 있었다**

하나가 사용자에게 닿는다. 판정 축이 보는 화면에 **사용자가 무엇을 요청했는지**가
들어간다. 사전등록 개정(`JUDGE_VIEW_USER_TURN_AMENDMENT_PREREG`)과 그 결과
문서를 함께 낸다.

### 왜

`render_trace_for_judge` 는 에이전트의 텍스트와 도구 호출만 냈다. **요청은 아예
없었다.** FM-3.2 는 그래도 됐다 — "고친 코드를 확인했나"는 행동만으로 답이
나오고, 요청을 한 번도 못 본 채 정밀도 0.9286 / 재현율 1.0000 을 냈다.

다음 축들에는 안 된다. FM-1.1(요청 불이행) · FM-2.3(과제 이탈) · FM-3.1(조기
종료)은 셋 다 **요청과 실제를 대조**해야 한다. 요청이 없으면 어려운 질문이
아니라 **물을 수 없는 질문**이다.

### 무엇이 들어가고 무엇이 안 들어가나

`USER ASKED:` 블록이 행동보다 먼저, 첫 등장 순서로, 중복 없이 들어간다.
프롬프트가 누적되므로 앞 턴이 뒤 호출마다 다시 나타나고, 두 번 본 턴은 사용자가
한 번 말한 것이다.

★ **`tool_result` 블록은 제외한다.** Claude Code 는 도구 결과를 `user` 롤
메시지에 담는다. 롤만 보고 고르면 40개 라벨 세션에서 **기계 출력 871건**이
*사람이 한 말*로 화면에 들어가고, 이미 상한이 있는 화면이 두 배가 된다.

### 측정 — 6개 예측 전부 통과

같은 40개 손라벨 세션, 밴드는 개정문이 **머지된 뒤에** 실행했다.

| | 예측 | 결과 |
|---|---|---|
| P1 | 정밀도 ≥ 0.8667 | **1.0000** |
| P2 | 재현율 1.0000 유지 | **1.0000** |
| P3 | 40건 중 37+ 판정 불변 | **39/40** |
| P4 | 환각 근거 0 | **0** |
| P5 | 파싱 실패 ≤ 2 | **1** |
| P6 | 세션당 비용 상승 < 5% | **$0.0046 무변** |

요청문은 **40/40** 화면에 들어갔다.

🔴 **P1 의 이동은 한 건이다.** 이전 실행의 유일한 오탐이 재발하지 않은 것이고,
양성 13건에서 한 건은 정밀도를 약 0.07 움직인다. **1.0000 은 이 집합의 천장
수치이고 개선으로 인용하면 안 된다.** 방어 가능한 주장은 음성 쪽 —
*요청문을 넣어도 답이 나빠지지 않았다.*

P3 이 이 문서가 존재한 이유다. 요청문은 "고친 코드를 확인했나"와 무관하므로
판정이 **안 움직여야** 정상이다. 움직였다면 관계없는 재료가 판정을 흔든다는
뜻이고, 그건 뒤이을 축들을 불신할 이유다.

### 게시된 수치가 자기 화면을 밝힌다

`0.9286` 은 요청문이 없던 화면의 값이다. 이번 릴리스로 **그 화면은 사라진다.**
그래서 리포트 문면과 CLI 도움말이 이제 두 수치와 각각의 화면을 함께 말한다 —
*"0.9286 without the request in the judge's view and 1.0000 with it; the two
differ by one session, so read them as unchanged rather than improved."*

일부러 `1.0000` 만 쓰지 않는다. 개정문 §6 은 P3 이 **실패할 때만** 교체한다고
썼는데 그건 미명세였다. 이유는 예측 결과와 무관하다 — 출하되는 화면이 바뀌면
옛 수치는 **제품이 더 이상 쓰지 않는 것을 설명**한다.

### 전송되는 것이 늘었다

화면은 판정마다 모델 제공자로 간다. 지금까지는 도구 input verbatim(경로·명령어)
과 에이전트 텍스트였고, 여기에 **사용자 본인이 입력한 요청문**이 더해진다.
같은 범주가 늘어난 게 아니라 **새 범주다.**

그래서 사전등록 §8 이 순서를 **문면 → 코드**로 못박았고, 웹 `/privacy` 가
양 로케일에서 먼저 갱신·배포된 것을 확인한 뒤에 이 릴리스를 냈다.
저장은 여전히 안 한다 — 바뀌는 것은 **전송**이다. 프로젝트 스위치를 내리면
축이 시작조차 하지 않으므로 요청문도 나가지 않는다.

## 0.5.8 — 2026-09-03 · **판정은 켜져 있었고, 부품이 없었다**

두 가지가 사용자에게 닿는다. 하나는 **오늘 새로 설치한 사람의 판정이 조용히
죽어 있던 것**이고, 하나는 리포트가 같은 말을 두 뜻으로 쓰던 것이다.

### 새로 설치하면 판정이 조용히 안 돌았다

`[judge]` extra 가 `anthropic>=0.30` 이었고 **위쪽 한계가 없었다.** `anthropic`
1.x 가 `Messages.create()` 에서 `temperature` 를 없앴고, 판정기 둘 다
`temperature=0.0` 을 넘긴다. 그래서 깨끗한 설치는 1.x 를 받아 **모든 판정이**
이렇게 돌아왔다:

```
verification: {enabled: true, judged: false, judge_calls: 1, judge_cost_usd: 0.0,
               not_judged_reason: "the judge did not answer"}
```

★ **이 실패는 조용한 종류다.** 판정기는 429 가 아닌 예외를 `parse_failed` 로
바꾸고, 축은 그걸 "판정 못 했음"으로 보고한다 — 화면에서 **"판정할 게 없었다"와
구분되지 않는다.** 2026-09-03 라이브 컨테이너에서 확인: `anthropic 1.3.0`,
`TypeError: Messages.create() got an unexpected keyword argument 'temperature'`.

그리고 **우리 코드는 한 줄도 안 바뀌었다.** 바뀐 것은 *언제 설치했는가* 하나다.
개발 기계는 몇 달 전에 해석된 0.109.2 를 갖고 있어서 같은 트레이스를 정상
판정했다. CI 초록불이 이 사고를 증명해주지 못하는 모양이다.

이제 `anthropic>=0.30,<1` 이다. 올리는 쪽이 아니라 **묶는 쪽**을 골랐다: 0.x 는
게시된 정밀도 수치 전부가 측정된 버전이고, `temperature=0` 은 리포트 문면에
적혀 있고 판정 사전등록 §3 이 동결한 값이다. 1.x 로 가는 것은 업그레이드가
아니라 개정이다.

가드는 **핀이 아니라 이유에 걸려 있다** — 코드가 `temperature` 를 넘기는 동안만
발동한다. 나중에 판정기가 이전하면 한계는 다시 열려도 되고, 테스트를 고쳐야
옳은 일을 할 수 있는 가드는 읽지 않고 고쳐진다.

### 리포트가 "탐지기별"을 두 뜻으로 썼다

`Breakdown by detector:` 아래 세 줄을 세고 나면 그 아래 절이 **"union of 4
detectors"** 라고 말했고, 둘을 맞춰볼 방법이 리포트 안에 없었다. 두 블록은 서로
다른 자료구조에서 오고 **멤버가 실제로 다르다**:

| 블록 | 멤버 |
|---|---|
| 비용 귀속 | `provable_duplicate` · `context_resend` · `redundant_read` · `semantic_duplicate` |
| 낭비율 합집합 | `repeat` · `context_resend` · `redundant_read` · `duplicate_creation` |

한 탐지기가 두 이름을 쓰고(`provable_duplicate` = `repeat`, 둘 다 cascade), 네
번째 멤버는 아예 다른 탐지기다. 이 결함이 발견된 트레이스에서 빠진 행은
`semantic_duplicate` — 돌지 않은 LLM 판정기였다.

★ 읽기 문제만이 아니었다. 저장 계층이 한 블록을 다른 블록의 이름으로 읽어
**저장된 모든 트레이스에서 `provable_duplicate` 의 바이트가 비어 있었고**, 그건
화면에서 "중복 바이트 없음"과 구분되지 않는다.

이제 비용 블록은 자기 넷을 이름으로 밝히고, **돌지 않은 탐지기는 행이 없다 —
여기서의 부재는 측정된 0이 아니다** 를 말하고, 다른 집합을 가리킨다. 낭비율
한 줄은 맨 "4 detectors" 대신 자기 넷이 어디 나열돼 있는지를 말한다.

문면만이다. 이름 통일은 동결된 사전등록 집합의 멤버를 옮기고 저장 어휘와
대시보드까지 닿으므로 **별개 트랙**이다.

## 0.5.7 — 2026-09-02 · **보내다 실패하면 잃었고, 볼 게 없으면 아무 말도 안 했다**

세 가지가 사용자에게 닿는다. 셋 다 "이미 알고 있던 것을 말하지 않던" 자리다.

### 실시간 알림이 한 번 실패하면 그 소견을 영구히 잃었다

`on_finding` 은 소견이 처음 기록되는 순간 **딱 한 번** 불렸다. 전송이 실패하면
다시 시도하지 않았고, 추적하라고 만든 `delivered` 필드는 선언만 있고 아무도
읽지 않았다.

이제 배달은 **원장을 훑는 단계**다. 매 스윕 뒤 아직 못 보낸 소견 전부를 다시
내보내고, **첫 시도와 재시도가 같은 호출**이다 — 서로 다르게 동작할 branch 가
없다. 재시도 주기는 이미 있는 감시 스케줄이라 새로 자는 코드가 없다.

★ **그리고 더 큰 것**: 감시기가 프로젝트별 키를 **버리고** 있었다
(`(project, root)` 로만 타겟을 만들어서). 그래서 전역 자격증명 파일로 되돌아갔고,
그 파일이 없으면 **모든 전송이 `no_key`** 였다. 있는 경우가 더 나쁘다 — 서버는
키로 프로젝트를 판단하므로 여러 프로젝트가 한 키로 보내면 **전부 한 곳에
기록된다**. 이제 각 소견이 **자기 프로젝트 키로** 나가고, 키가 없는 프로젝트의
소견은 옆 프로젝트 키로 보내는 대신 **아예 안 보낸다**.

포기 카운터는 없다. 대신 실행 로그에 `pending=N` 과 마지막 이유가 남는다 —
영구 실패가 1분마다 시끄러운 쪽이, 두 번 조용해지는 쪽보다 낫다.

### 도구 호출 기록이 없는 트레이스가 "낭비 없음"이라고만 말했다

도구 span 을 하나도 못 받으면 도구 반복 탐지기는 볼 것이 없다. 그런데 리포트는
`no waste detected` 만 찍고 **그 사실을 한 줄도 말하지 않았다.** "볼 게 없었다"와
"봤는데 깨끗했다"가 같은 문장이었다.

이제 그 경우 이렇게 말한다:

> **Tool mapping coverage for this trace**: no tool calls were recorded, so the
> tool-repeat detectors had nothing to examine — this is not a finding of zero
> waste. If this agent does call tools, its instrumentation may not be emitting
> tool spans.

측정된 프레임워크 셋이 그 상태다 — 계측기가 도구 span 을 안 내보내는
**Haystack · Google GenAI · Anthropic 직접 SDK**. 도구가 있는 트레이스의 리포트는
**바이트까지 그대로**다 (실 트레이스 12건 대조).

### 탐지기별 절대 비용이 계산되고 버려졌다

`waste_rate.per_detector` 는 비율만 내보냈다. 절대 비용은 계산된 뒤
직렬화에서 사라졌고, 그 때문에 저장 계층이 `duplicate_creation` 의 행을 만들 수
없어 **대시보드가 그 탐지기를 아예 보여줄 수 없었다.**

이제 네 탐지기 모두 `waste_cost` 를 담는다. **숫자가 커지지는 않는다** — Claude
Code 트레이스에서 도구측 비용은 구조적으로 0이다(도구 span 에 토큰수·요율이
없다). 사는 것은 **0으로 측정된 것**이 **저장 안 된 것**과 구분된다는 것이다.

### 안 바뀐 것

탐지 로직 · φ · N · 임계값 · 게시된 모든 수치 · 요율표. 그리고 리포트의 다른
모든 필드 — 새 키를 빼면 JSON 이 이전과 완전히 동일하다(12건 대조).

## 0.5.6 — 2026-09-01 · **틀린 요금이 "정확함"이라고 적혀 나가고 있었다**

이번 판의 이유는 새 기능이 아니라 **정정**이다. 네 모델의 요율이 틀렸고, 그중
둘은 실제의 3분의 1이었고, 리포트는 그 숫자에 `accuracy_flag: accurate` 를
붙여 내보내고 있었다.

### 정정: 요율 네 건

| 모델 | 쓰던 값 | 실제 | |
|---|---:|---:|---|
| `claude-opus-4-1` | 5.0 | **15.0** | 3배 과소 |
| `claude-opus-4` | 5.0 | **15.0** | 3배 과소 |
| `claude-haiku-3-5` | 3.0 | **0.80** | 3.75배 과대 |
| `claude-mythos-5` | 3.0 | **10.0** | 3.3배 과소 |

넷 다 **조용했다**. 가격표에 없는 모델은 접두 별칭으로 가장 가까운 이름에
붙는데, 그 매칭이 `matched=True` 를 돌려주기 때문에 경고도 안 나가고
`unpriced_models` 에도 안 실렸다. `claude-opus-4` 별칭에는 주석까지 달려
있었다 — *"falls to nearest known Opus"* — 그리고 가장 가까운 Opus 는 Opus 4
값의 3분의 1이었다.

Anthropic 공식 가격 페이지를 그날 받아 대조했고, **이미 표에 있던 항목 일곱은
전부 정확했다**. Opus 4.5 / 4.6 / 4.8 은 일부러 4.7 항목으로 그대로 둔다 —
요율이 같고, 별도 항목을 만들지 않기로 한 결정이 사전등록에 남아 있다.

**게시된 수치는 하나도 안 움직인다.** Corpus A 28 세션을 다시 재서 분모·분자·
`union_wr_char` 전부 비트 동일을 확인했다. 어떤 코퍼스도 이 네 모델을 쓰지
않기 때문이고, 그것이 이 크기의 정정이 게시 수치를 안 건드리는 이유다.

### 정정: 리포트 푸터 문면

푸터가 *"unknown models fall back to Sonnet 4.5"* 라고 적고 있었다. 접두 별칭에
걸리는 모델에는 거짓이다 — Sonnet 이 아니라 **다른 모델의 요율**을 쓴다. 실제
동작대로 다시 썼고, **대체가 보고되는 경우와 안 되는 경우**를 문장이 스스로
말하게 뒀다.

같은 줄의 *"Range spans cache-hit (lower) to cache-miss (upper)"* 는 **맞다.**
같은 토큰 수에 대한 두 가지 실제 청구 결과이고, 비율이 아니다. 확인 후 그대로
뒀다.

### 추가: `boxdawn watch` — 세션이 도는 중에 반복을 찾는다

분석기는 이미 사용자 기계에 있다. 세션이 끝나기를 기다릴 이유가 없다.

```
boxdawn watch --install     OS 스케줄러에 1분 간격으로 등록
boxdawn watch --status      등록 상태와 지금까지 찾은 것
boxdawn watch --once        한 번 돌고 끝
```

반복이 일어나고 **기록되기까지 중앙값 32.5초** (기존 서버 경로는 43분).
그중 스캔은 0.36초이고 나머지는 다음 폴링을 기다리는 시간이다.

★ **아무것도 보내지 않는다.** 발견은 `~/.clew/live_findings.json` 에만 적히고,
보낼 엔드포인트 자체가 없다. 배달은 손라벨 정밀도 게이트를 통과해야 열리고,
아직 열리지 않았다.

알림 대상은 **부작용이 없는 도구**로 한정된다 — 같은 파일을 다시 읽는 것은
낭비지만, `make` 를 다시 돌리는 것은 30번 고친 뒤의 확인이다. 손라벨 실측:
읽기 계열 21/21, 셸 계열 0/7.

### 추가: `boxdawn analyze --verification` (옵트인)

세션이 고친 코드를 확인했는지 묻는다. 손라벨 40 세션에서 **정밀도 0.9286 ·
재현율 1.0000**.

세션당 **한 번** 호출하고 **$0.0046 · 1.8초**. 사용자의 `ANTHROPIC_API_KEY` 를
쓰기 때문에 **기본은 꺼져 있다**.

결과가 셋이고 세 번째가 중요하다: 확인함 / 확인 안 함 / **판정 불가**. 키가
없거나 호출이 실패하면 **"판정 불가"** 이지 "확인 안 함"이 아니다. 이 축을
대체한 규칙이 정확히 그 뭉갬 때문에 정밀도 0.3250 으로 죽었다. 키가 없어도
종료 코드는 0 이다.

### 수정: 서버 상한이 올랐는데 제출이 그걸 몰랐다

413 을 받은 파일은 **거부당했던 크기**와 비교되고 있었다. 서버 상한이
10 MB → 16 MB 로 올라도 그 파일은 영원히 재시도되지 않았다. 이 기계에서
12.25 MB 세션 하나가 그렇게 모든 측정 밖에 있었다.

이제 서버에 **지금 얼마까지 받는지** 묻는다. 장부에 거부 기록이 있을 때만
묻기 때문에, 거부당한 적 없는 기계는 요청을 보내지 않는다.

## 0.5.5 — 2026-08-30 · **설치를 끝까지 갈 수 있게 되었다**

0.5.4 는 `submit` 을 줬지만, 그걸 쓰려면 설정 파일 두 개를 손으로 써야 했다.
이번 판은 그 사이의 빈칸을 메우고, 제출이 사람 손 없이 돌게 만든다.

### 추가: `boxdawn setup`

키를 받고 나서 제출이 돌기까지의 한 걸음. 인자 없이 실행하면 이 기계의 트레이스
폴더를 **사람이 읽을 수 있는 이름으로** 보여주고 아무것도 쓰지 않는다.

```
 #  project                      sessions  last activity
 1  Custos - clwe project              39  2026-08-30
 2  CUSTOS PAGE HTML                   18  2026-08-30
```

Claude Code 는 폴더를 `C--Users-User-Desktop-Custos---clwe-project` 처럼 이름 붙인다.
설정하려고 그걸 해독할 이유는 없다. 세션 파일마다 실행된 디렉터리가 적혀 있어서,
읽을 수 있는 이름은 이미 데이터 안에 있었다.

`--key` 로 단일 키 설정을, `--project` 를 더하면 코드베이스별 설정을 쓴다.
키는 **모양만** 검사하고 명령이 그렇다고 말한다. 살아 있는 키인지는 서버만 답할 수
있고, 확인한 척하는 것은 침묵보다 나쁘다.

### 추가: `boxdawn submit --install`

시간마다 도는 제출을 OS 스케줄러에 등록한다. 상주 프로세스가 아닌 이유는
**죽은 데몬이 조용한 데몬과 똑같아 보이기** 때문이다. 매 실행이 한 줄을 남기고
(보낼 게 없던 실행도), `--status` 가 그걸 되읽는다.

**켜는 것이 백필이 되지 않는다.** 설치 시점을 기록하고 그 뒤에 조용해진 세션만
자동으로 보낸다. 과거분은 `boxdawn submit` 으로 사람이 요청할 때만 간다.
백필된 세션은 분석한 날짜를 달고 쌓여 하루치 봉우리를 만들기 때문이다.

Windows 는 실제로 등록한다. macOS 와 리눅스는 **붙여넣을 줄을 출력만** 한다.
검증할 수 없는 등록이 조용히 실패하는 것이 이 설계가 피하려는 바로 그것이다.

### 추가: 코드베이스별 라우팅 (`~/.clew/projects.yaml`)

`submit` 은 `~/.claude/projects` 전체를 한 키로 보냈다. 알림 규칙은 **같은 기준선
안에서** 어제와 오늘을 비교하는데, 두 코드베이스가 한 통에 섞이면 그 비율은
"오늘 어느 프로젝트를 했는가"를 답하게 된다. 이제 코드베이스마다 자기 키를 갖는다.
설정 파일이 깨져 있으면 단일 키로 **폴백하지 않고 거부한다.** 폴백이 곧 그 섞임이다.

### 추가: 리포트가 무엇을 근거로 계산했는지 말한다

어댑터는 트레이스의 일부를 버리거나 바꿔 써 왔고, 그것을 stderr 로만 알렸다.
호스팅 분석에는 stderr 를 읽는 사람이 없다. 이제 리포트가 말한다.

```
## What the numbers were computed on
- **1 tool call dropped**: the call was made but no result was recorded.
```

깨끗하게 읽힌 파일에는 **이 절이 아예 없다.** 절이 있다는 것 자체가 신호다.
실 세션 71개로 재보니 §29.1 회복은 1건에서, 비-text 결과 치환은 49건에서 발동했다.

### 문면: 출력에서 줄표를 걷어냈다

리포트와 CLI 가 내보내는 문장에서 `—` 를 전부 없앴다. 문자만 지우면 문장이 깨지므로
자리마다 다시 썼다. 독립절 둘이면 마침표, 목록이나 정의를 열면 콜론, 삽입구면 괄호다.
82곳이고, 코드 주석과 문서 문자열은 건드리지 않았다.

### 수정

- `Discovered.label` 이 **어느 OS 에서 읽어도 같은 이름**을 낸다. `Path` 는 자기가
  도는 OS 의 구분자만 알아서, 윈도우에서 기록된 경로를 리눅스에서 읽으면 통째로
  돌려줬다. 호스팅 분석기가 리눅스에서 돌고 트레이스는 노트북에서 오므로 이건
  예외가 아니라 정상 경로다.
- `pip install 'clew[detect]'` 와 `'clew[adapter]'`. **없는 패키지 이름**이었다.
  그대로 친 사용자는 설치에 실패했다.
- 설정 항목을 **경로로** 대조한다. 문자열로 비교하면 `C:/Users/...` 와
  `C:\Users\...` 가 다른 것이 되어 같은 폴더가 두 번 들어가고, 그러면 다음 실행에서
  파일 전체가 거부된다. 키 하나 바꾼 것이 **모든 프로젝트의 제출을 멈춘다.**

### 측정

네 번째 코퍼스를 더했다. `union_wr_char` **0.7993** (859 트레이스, MIT).
사전등록한 예측 `[0.80, 0.95]` 이 **0.0007 차이로 빗나갔고 그대로 공개했다.**
짧은 세션에서는 재전송 비중이 작다는 것이 드러났고, 길이별로 단조 증가한다
(도구 1~2회 0.3487, 11회 이상 0.8802). 헤드라인은 범위를 넓히는 대신
"긴 세션에서는" 으로 좁혔다.

## 0.5.4 — 2026-08-28 · **세션을 자동으로 보내고**, 요율이 진짜였는지 함께 말한다

두 갈래다. 하나는 새 명령 두 개 — 끝난 세션을 사람 손 없이 보내는 `submit` 과,
어떤 트레이스가 무거운지 미리 재는 `estimate`. 다른 하나는 **비용 숫자가 어디까지
믿을 만한지**를 리포트가 스스로 말하게 만든 것이다.

### 추가 — `boxdawn submit`

조용해진 지 오래된 세션을 찾아 한 번씩 보낸다. 무엇이 "끝난 것"인지는 여기서 고르지
않고 **사전등록**한다: [`docs/SESSION_CLOSE_RULE_PREREG.md`](https://github.com/boxdawn/boxdawn/blob/main/docs/SESSION_CLOSE_RULE_PREREG.md)
(240분 · `trace_id` 당 1회 · 하위 에이전트 트레이스까지 재귀 탐색 — 한 단계만 훑으면
측정 코퍼스에서 **84개 중 13개**를 놓친다).

**무거운 트레이스에 천장이 없다.** 분석 시간은 파일 크기가 아니라 **누적 컨텍스트**를
따라간다 — 실측 368~440 s/GB. 5.24 MB 트레이스가 40초, 3.39 MB 가 85초였다. 그래서
크기 상한은 되는 트레이스를 거절한다. 서버가 작업을 접수하고 티켓을 주며, CLI 는 짧은
요청으로 물어본다. **어떤 요청도 길게 열려 있지 않다.**
- 프로젝트 키가 필요하다: `BOXDAWN_API_KEY` 또는 `~/.clew/credentials.yaml`
- 중간에 끊겨도 다시 돌리면 이어진다. **같은 세션을 두 번 보내지 않는다**
- 실패한 전송은 다시 시도한다 — HTTP 오류는 `run` 행을 하나도 만들지 않으므로
  R2("한 `trace_id` 는 한 번")와 충돌하지 않는다. 그전에는 실패가 "보냈음"으로
  기록되어 **그 세션이 영구히 유실**됐다

⇒ **이 릴리스가 브라우저에서 발급한 키의 사용 경로를 처음으로 연다.** 키 발급·폐기는
이전부터 작동했지만 발급받은 키로 트레이스를 보낼 도구가 배포본에 없었다 — 키를 만들고
갈 곳이 없었다. `submit` 이 그 길이다.

### 추가 — `boxdawn estimate`

트레이스가 왜 무거운지 내고 **판정은 하지 않는다.**

```
$ boxdawn estimate trace.jsonl --json
{"trace_id": "...", "file_bytes": 327550,
 "cumulative_context_bytes": 2105068, "llm_calls": 39,
 "spans": 46, "parse_seconds": 0.785}
```

**"너무 크다"를 말하지 않는 것이 설계다.** 얼마가 너무 큰지는 묻는 쪽의 천장에 달렸고
(브라우저 업로드는 사람이 기다리고, 무인 큐는 아무도 기다리지 않는다) 여기서 계산한
문턱은 **어느 천장에서 나온 것인지 숨긴 채** 모든 소비자에게 전파된다. 값은 분석기가,
판정은 부르는 쪽이 한다. 출력에 판정이 없다는 것을 테스트가 단언한다.

파싱만 하므로 전체 분석의 **2.4~3.0%** 비용이다.

### 추가 — 요율이 가격표에서 온 것인지

`cost_summary` 에 두 필드가 붙는다:

- **`rate_from_table`** (bool) — 모든 요율이 가격표에서 왔는가
- **`unpriced_models`** (list) — 대체된 모델 이름. 예: `["kinetic-0715"]`

**`accuracy_flag` 가 이 질문에 답하지 않는다.** 그 값의 뜻은 사전등록 5.1 대로
*"모든 호출에 티어 분할 토큰이 있었다"* 이고, **모델을 가격표에서 못 찾아도 그 조건은
참이다.** `get_pricing` 은 미지 모델에 기본값을 돌려주고 경고는 stderr 로만 나가므로
리포트를 읽는 쪽은 알 방법이 없었다.

실측(2026-08-27): 저장된 74건 중 **27건**이 대체 요율을 썼고 **전부
`accuracy_flag: accurate`** 였다. 그중 **25건이 Claude Opus 5** — 실제 토큰을 가진
호출이다. 기본값이 Sonnet 4.5 이고 그건 Opus 요율의 **60%** 이므로, 그 25건의 금액은
근사값이 아니라 **하한**이다. 나머지는 0토큰 `<synthetic>` 이라 금액에 영향이 없다.

⇒ **기존 `accuracy_flag` 의 뜻은 바꾸지 않았다.** 사전등록된 정의를 코드에서 다시
정하는 것은 개정이므로, 새 필드를 옆에 두고 **둘이 어긋날 수 있게** 했다. 그게 요점이다.

0토큰 대체는 보고하지 않는다. Claude Code 는 API 호출이 아닌 메시지에 `<synthetic>` 을
쓰고 그건 항상 토큰이 0이므로, 표시하면 **정확한 금액에 각주를 붙이는** 셈이 된다.

### 추가 — 가격표: Claude Opus 5 · Sonnet 5 · Fable 5

출처: <https://platform.claude.com/docs/en/about-claude/pricing> (2026-08-27 확인)

| 모델 | base in | 5m write | 1h write | cache read | out |
|---|---|---|---|---|---|
| Claude Opus 5 | $5 | $6.25 | $10 | $0.50 | $25 |
| Claude Sonnet 5 | $2 | $2.50 | $4 | $0.20 | $10 |
| Claude Fable 5 | $10 | $12.50 | $20 | $1 | $50 |

`claude-opus-4-8` 별칭도 명시했다. 그전에도 `claude-opus-4` 접두사로 해결되어 **우연히
맞는 값**이 나왔는데, 4.7 과 4.8 이 갈리는 날 고쳐야 할 줄이 보이지 않았다.

### 변경 — 키를 못 찾았을 때 무엇이 문제인지 말한다

`read_key` 는 다섯 가지 이유로 실패하는데 메시지는 그중 하나만 말했다. 파일이 있고 키도
적혀 있는 사람이 **이미 쓴 파일을 쓰라는 안내**를 받았다.

가장 흔한 원인: `api_key:bdk_...` — **콜론 뒤 공백 없음.** YAML 은 그 공백을 요구하므로
줄 전체가 문자열 하나로 파싱되고, 아무 곳도 "공백"이라는 단어를 출력하지 않았다.
**공백을 의심하는 사람은 없다.** 이제 다섯 원인을 각각 말하고, 같은 파싱 실패를 내는 두
실수(공백 없음 / 키만 붙여넣음)도 구분한다.

그리고 **환경변수가 파일보다 우선하며**(CI 를 위해 의도된 순서다) **레지스트리에서 지운
변수는 이미 실행 중인 프로세스에 닿지 않는다** — 그 셸까지 포함해서. 두 가지가 겹쳐
한 시간 전에 폐기한 키로 401 을 받는 일이 생겼다. 두 출처가 동시에 있을 때만 어느 쪽을
쓰는지 한 줄로 알린다. **키 자체는 절대 출력하지 않는다.**

### 변경 — 패키지 메타데이터가 제품을 가리킨다

- `Homepage` → <https://boxdawn.com> (전에는 이 저장소를 가리켰고 `Repository` 와 같은
  URL 이었다 — PyPI 에 코드 링크가 둘이고 서비스 링크가 없었다)
- `Documentation` → <https://boxdawn.com/product>
- **`license` 필드를 채웠다.** MIT 분류자는 있었고 필드는 비어 있어서, 분류자가 아니라
  필드를 읽는 도구에는 **라이선스 없는 패키지**로 보였다

빌드한 wheel 의 `METADATA` 를 읽어 확인했다(소스만 믿지 않았다). 같은 확인에서 부수로:
`Requires-Dist: tiktoken<1.0,>=0.7` — extra 마커가 없으므로 **`pip install boxdawn` 만
해도 tiktoken 이 깔린다.** 게시 수치가 깨끗한 설치에서 재현된다.

### 사전등록

- **알림 축을 `occurred_at` 으로** — §3 이 shadow-mode 측정을 `trace_started`(실행 시각)
  순서로 만들었는데 §2/§6 은 라이브 축을 `analyzed_at`(도착 시각)으로 얼려뒀다. 한 축에서
  측정하고 다른 축에서 발동하는 규칙은 측정된 규칙이 아니다.
- **`max_volume_ratio = 5.0`** — 두 창의 입력 바이트가 5배 안일 때만 비교한다. 351개 날
  쌍에서 `|Δwr|` 중앙값이 1x~5x 에서 0.21~0.34pp 로 평평하다가 5~10x 에서 4배로 뛴다.
  절대값 하한을 올리는 대안은 **적게 쓰는 사용자를 전부 침묵시킨다** — 하루 3MB 쓰는
  프로젝트는 5MB 하한에서 모든 날을 잃는다.

### 호환성

- 리포트 최상위 키 수 무변. `cost_summary` 에 **중첩 키 2개 추가**.
- **임계값·탐지기·φ·N·embed_model 무변.** 가격표 추가는 그 모델을 쓰는 트레이스의 비용만
  바꾼다 — 동결 코퍼스(Toolathlon · B · C)에는 해당 모델이 없어 수치 무변.
- 이미 저장된 run 의 비용은 재계산되지 않는다. 가격표 수정은 **앞으로만** 고친다.
- 모르는 키를 무시하는 소비자는 영향받지 않는다.
- ★ **이 릴리스는 저장 계층에서 비교 단위를 새로 연다.** `params_key` 는
  `md5(phi:n_window:embed_model:analyzer_version)` 생성 컬럼이고 `analyzer_version` 은
  설치된 배포본의 버전이다. 0.5.4 로 분석기가 재배포되면 새 run 은 **새 `params_key`**
  로 들어가고, 기존 run 은 그대로 남되 새 것과 같은 선에 놓이지 않는다. 가격표가
  바뀌었으므로 **비용 축은 실제로 비교 불가**이며 이는 가드가 제 일을 한 것이다 —
  다만 추세선은 여기서 다시 시작한다.

## 0.5.3 — 2026-08-24 · 비율만 있던 자리에 **분자와 분모**를 함께 싣는다

`waste_rate` 블록이 `union_wr_char` 와 `union_wr_cost` 는 발행하면서 그 비율을
만든 수는 내보내지 않았다. 한 트레이스만 보는 사람에게는 충분하지만, **여러
트레이스를 모으는 사람에게는 쓸 수 없는 값**이다 — 비율의 평균은 합의 비율이
아니다. 되돌리기도 반만 가능했다: `union_waste_bytes` 는 6자리로 반올림된
비율에서 복원할 수 있었지만(손실 있음), `union_waste_cost` 는 **분모
(`total_input_cost`)가 블록에 없어서 아예 복원 불가**였다.

### 추가

- **`waste_rate.total_input_cost`** — union 비용 비율의 분모.
- **`waste_rate.union_waste_bytes`** — 문자 비율의 분자.
- **`waste_rate.union_waste_cost`** — 비용 비율의 분자.

### `cost_summary.total_waste_cost` 는 대체물이 아니다

두 값이 같아 보이는 트레이스가 있어도 **출처가 다르다.**

| 값 | 어떻게 만들어지나 |
|---|---|
| `cost_summary.total_waste_cost` | 디텍터별 breakdown 의 합 |
| `waste_rate.union_waste_cost` | 스팬 단위 union + `DETECTOR_ORDER` tie-break + `context_resend` 의 청크 비용 |

실 Claude Code 세션 8건에서 두 값이 일치했다 — 8건 모두 cascade 가 기여하지
않았고, 기여 디텍터가 둘인 유일한 트레이스에는 스팬 겹침이 없었다. 즉 이건
**계산 방식에 대한 진술이고 관측된 불일치가 아니다.** 그래도 한쪽을 다른 쪽으로
읽으면 안 된다.

### 호환성

- **중첩 키 추가다.** 최상위 키 수는 22 로 무변. **임계값·탐지기·판정 기준 변경
  없음** ⇒ 사전등록 개정이 발동하지 않는다 (`trace_started` 와 같은 부류).
- 모르는 키를 무시하는 소비자는 영향받지 않는다.

### 이 항목이 늦게 쓰인 이유

릴리스 커밋 `dbc3245` 가 **`pyproject.toml` 한 줄만** 바꿨다. 버전은 올라갔고
이 파일은 갱신되지 않아서, `0.5.3` 이 PyPI 에 있는 동안 CHANGELOG 의 최신
항목은 `0.5.2` 였다. 2026-08-27 에 발견하고 소급 기록한다 — 릴리스 절차에
CHANGELOG 단계가 없었던 것이 원인이고, 항목을 빼먹은 판단이 아니다.

## 0.5.2 — 2026-08-22 · 트레이스가 **언제 실행됐는지**를 리포트가 실어 보낸다

리포트에 실리는 시각은 `analyzed`(우리가 분석을 돌린 시각) 하나뿐이었다. 리포트를 시계열로 쌓는 소비자가 그것을 축으로 쓰면, 오래된 트레이스를 오늘 몰아서 분석했을 때 전부 오늘 자리에 찍힌다.

### 추가

- **`trace_started`** — 리포트 JSON 최상위 필드. `min(span.start_time)` 을 UTC 로 정규화한 값이다. `Span.start_time` 은 tz-aware 임이 검증되고 `Trace` 는 span 을 최소 1개 요구하므로 이 값은 항상 존재한다.

공개 트레이스 `davanstrien/agent-race-traces` / `claude-code.jsonl` 에서 두 시각의 거리:

| 필드 | 값 |
|---|---|
| `trace_started` | `2026-05-01T13:22:29Z` |
| `analyzed` | `2026-08-22T07:13:21Z` |

**113일 차이다.** 축을 `analyzed` 로 잡은 시계열은 이 트레이스를 8월에 일어난 일로 그린다.

### 호환성

- 추가 필드다. **임계값·탐지기·판정 기준 변경 없음.** 마크다운 리포트는 무변.
- 같은 트레이스의 이전 리포트와 키 단위로 대조했다: **신규 키 1개 외 차이 없음.** `waste_ratio` 0.659536 · `total_analyzed_cost` 2.5248795 · `total_waste_cost` 1.66524903 · `accuracy_flag` accurate 전부 무변.
- 모르는 키를 무시하는 소비자는 영향받지 않는다.

## 0.5.1 — 2026-08-20 · 리포트가 자기 계산을 정확히 설명하게 만들기

이 릴리스는 탐지 결과가 아니라 **그 결과를 설명하는 말**을 고친다. 네 건 다 계산은 맞고, 문면이 내가 무엇을 재는지 말하지 않거나 낡은 동작을 설명하고 있었다.

### 변경

- **`Waste detection` 라벨이 범위를 밝힌다** → `Waste detection (tool cascade)`. 그 플래그(`wasteful`)는 repeat/pingpong detector 만 반영하고 `context_resend` 를 반영하지 않는다. 그래서 낭비가 전부 context resend 인 트레이스에서 리포트가 `Total waste (detected): $1.665249 (66.0%)` 바로 아래에 `no waste detected` 를 찍었다. 두 진술 다 맞지만 라벨이 범위를 안 담아 서로를 부정하는 것처럼 읽혔다.
- **각주가 실제 가격 산정을 설명한다.** `Attribution assumes Sonnet pricing.` → `Attribution uses per-model rates; unknown models fall back to Sonnet 4.5.` Toolathlon / Exgentic cost table 확장 이후 `pricing.py` 는 alias 로 모델별 요율을 해결하고 모르는 모델만 fallback 한다. 각주가 자기 계산을 오설명하고 있었다.
- **`cost_summary.accuracy_flag` 가 LLM 호출 0건 트레이스에서 `accurate`** 가 된다 (전: `estimated`). 사전등록 기준은 *"모든 LLM 호출이 tier-split 을 가질 때만 accurate"* 이고, 공집합에서 그 전칭명제는 공허하게 참이다. 해당 줄의 주석은 이미 그렇게 적혀 있었고 코드가 반대로 동작했다.
- **어댑터가 표시한 부재(absence) 센티넬을 cascade 가 건너뛴다.** 새 필드 `Span.output_is_absent` (기본 `False`). Claude Code 는 명령이 아무것도 출력하지 않으면 그 자리를 `(Bash completed with no output)` 로 채우는데, 비어 있지 않으므로 tool 출력 불변식을 통과한 뒤 sha256 게이트가 *"출력 없음"* 두 건을 서로의 중복으로 판정한다. 같은 원칙은 non-tool 분기에 이미 있었다. 벤더 문자열은 어댑터에만 산다.

### ★ `tiktoken` 을 의존성으로 선언 — 사용자 수치가 우리 수치와 일치하게 된다

`tiktoken` 은 0.5.0 까지 **어느 의존성·extra 에도 선언되지 않았다.** `context_resend` 와 `redundant_read` 는 토큰 수를 셀 때 `tiktoken` 을 시도하고 없으면 `len(text) // 4` 로 대체하는데(코드에 명시된 의도된 동작), 선언이 없었으므로 **모든 깨끗한 설치가 대체 경로를 탔다.** 우리 개발 환경에는 tiktoken 이 우연히 있었다. 그래서 우리가 발표한 토큰·비용 수치는 정밀 경로 값이고, 사용자가 같은 트레이스를 돌려 얻는 값은 대체 경로 값이었다.

공개 트레이스 `davanstrien/agent-race-traces` / `claude-code.jsonl` 로 측정한 차이:

| 수치 | 0.5.0 (대체 경로) | 0.5.1 (선언 후) |
|---|---|---|
| `total_waste_cost` | 1.68473586 | **1.66524903** |
| `waste_ratio` | 0.667254 | **0.659536** |
| `context_resend` resent input tokens | 2,069,799 | **2,056,739** |
| `waste_rate.union_wr_cost` | 0.150515 | **0.148774** |
| `total_analyzed_cost` | 2.5248795 | 2.5248795 (무변) |
| resent chunk 수 · 분모 | 1720 / 2,238,628 | 동일 (무변) |
| `waste_rate.union_wr_char` | 0.96584 | 동일 (무변 — 바이트 기반) |

**0.5.0 에서 올라오는 사용자는 토큰·비용 수치가 위 방향으로 바뀐다.** 탐지 판정(무엇이 낭비인지)은 바뀌지 않는다 — 바뀌는 것은 그 낭비를 토큰으로 환산하는 자의 정밀도뿐이다. 바이트 기반 수치(`union_wr_char`)와 개수 기반 수치는 전부 무변이다.

`tiktoken>=0.7,<1.0` (base 의존성). 정확 핀을 쓰지 않은 이유: 재현성은 인코딩 이름이 담보하며 그것은 코드에 동결되어 있다 (`context_resend.py :: _chunk_token_len`, `cl100k_base` · "frozen for v1"). 버전 범위는 라이브러리 존재만 보장한다.

### 사용자가 알아차릴 수 있는 동작 변화

- **Claude Code 트레이스에서 `waste_span_count` · `waste_details` · `category_counts` 가 줄어든다.** 실측: 로컬 40 세션 합계 31 → 9. 사라진 22건은 전부 부재 표현이다 (`(Bash completed with no output)` 20건 · `No matches found…` 2건).
- **`waste_rate.union_wr_char` 가 플래그 해제된 바이트만큼 내려간다.** 실측 한 트레이스에서 0.989674 → 0.989671 (−3.0e-06 · 6 span × 31 바이트). 소수 1자리 인용은 불변.
- **`io.save_trace` 가 쓰는 트레이스 파일에 `output_is_absent` 키가 실린다.** 구 파일은 기본값으로 계속 로드된다. **리포트 JSON 스키마는 변경 없다.**

### 무변경 (실측 대조)

- **비용 계산 전부.** 한 트레이스 전/후 JSON 필드 대조에서 9개 필드 전부 동일: `total_analyzed_cost` 24.0530675 · `total_waste_cost` 20.69691232 · `waste_ratio` 0.860469 · `detector_breakdown` 3개 전부.
- **동결 파라미터** φ=0.514345 · N=2 · embedding model rev `e8f8c211…`.
- **리포트 JSON 스키마** — 전/후 최상위 키 집합 동일. `coverage_stats` 동일.
- **Toolathlon 트레이스의 cascade 탐지** — 240 트레이스 표본에서 347 → 347. 거기서는 부재 센티넬이 없고 플래그가 실제 중복이다 (`emails-send_email` 139건 등).
- **CLI 인터페이스 · 의존성** 무변경.

### 릴리스 이유

네 건 다 계산은 맞으면서 문면이 틀린 사례였다. 같은 계측을 0.4.1 에서 한 번 다뤘다 (`wasteful=False` 일 때 상단이 duplicate creation 을 가렸던 것). 0.5.1 은 그 남은 절반이다 — 라벨 자체가 범위를 담은 것.

사전등록: `docs/CASCADE_ABSENCE_SENTINEL_AMENDMENT_{PREREG,RESULTS}.md`.
해당 PR: #119 · #120 · #122.

## 0.5.0 — 2026-08-17 · Rebrand to Boxdawn

### ★ Breaking (packaging + CLI)

- **PyPI package renamed:** `clew-custos` → `boxdawn`. Install with `pip install boxdawn` (previously `pip install clew-custos`). Users on `clew-custos` remain functional at the last published version (0.4.1) but will not receive further updates under that name.
- **CLI entry point renamed:** `clew analyze …` → `boxdawn analyze …`. The old `clew` script is no longer installed. `python -m clew analyze` still works as a fallback because the Python module name is unchanged.
- **Report header:** `# Clew Waste Report` → `# Boxdawn Waste Report`. CI scripts that grep the header must be updated.

### 무변경

- **Python import path:** `import clew` (and every submodule underneath) is unchanged. Existing user code that does `from clew.metrics import compute_waste_rate` continues to work without modification.
- **User config file name:** `clew.yaml` is kept for backward compatibility with existing configs. Not renamed to `boxdawn.yaml`.
- **Detection logic · frozen parameters:** φ=0.514345, N=2, embedding model rev — all unchanged. sha256 gates, cascade, WR_char / WR_cost / SDR@10 all bit-identical.

### 릴리스 이유

Rebrand from Clew (product) + Custos (company) two-name structure to a single Boxdawn brand. The product domain `hubble.ai` (originally paired with the Clew name after 6 branding attempts) was already held by a live YC-backed healthcare SaaS at rebrand time, breaking the domain anchor. Unifying to Boxdawn (company = product = `boxdawn.com` / `boxdawn.ai`) eliminates the two-name overhead for early-stage brand build.

## 0.4.1 — 2026-08-03

### 변경

- 리포트 상단 `## Result` 배너가 두 축을 함께 표시한다: **Waste detection** 과 **Duplicate creation check**. 이전에는 `wasteful=False` 일 때 상단이 `no waste detected` 만 찍고 duplicate creation 결과는 하단에만 있어서, 중복 생성이 탐지된 트레이스에서도 상단이 "낭비 없음" 으로 읽혔다. 이번 릴리스는 그 자기 모순을 없앤다.
- `## Result: WASTE DETECTED` 헤더가 `## Result` + `Waste detection: N wasteful span(s).` 로 통일. cascade=True / cascade=False 두 브랜치가 같은 문면을 쓴다.
- Duplicate creation check 요약은 항상 세 숫자 (`differ` / `same` / `no_id`) 를 분리 표시한다. 절대 하나의 합계로 접지 않는다.
- Framed as **"Detection, not confirmed impact."** — cascade waste 와 duplicate creation 을 같은 신뢰도 층으로 취급하지 않는다.

### 무변경 (sha256 검증)

- 탐지 로직 — cascade / structural / semantic / `_ID_BRIDGE_MAPPING` / `scan_id_bridge_candidates` 무수정.
- 동결 파라미터 — φ=0.514345, N=2, model rev `e8f8c211…`.
- `waste_details` · `between_window_counts` · `id_bridge_candidates` · `waste_span_count` · `wasteful` 다섯 필드의 report.json sha256, 두 검증 트레이스 (grok-4_2 line 83, claude-4-sonnet-0514_1 line 4) 에서 전부 동일.
- Duplicate creation check 섹션 본문 (`ID_BRIDGE_PRODUCTION_PREREG.md` §1.4 frozen) — 섹션 헤더, 서두 문단, per-candidate 3-way 문면 (`differ` / `same` / `no_id`) 무수정.
- report.json 스키마 · CLI 인터페이스 무변경.
- `tests/test_between_window.py` §3.2 금지어 가드 (`confirmed waste` / `verified waste` / `proven waste` / …) 유지. "provable" 단어 렌더러에 미사용 유지.

### 테스트 갱신 (회귀 아님, 계약 변경)

- `test_coverage_line_a_present_in_waste_detected` · `test_coverage_line_c_renders_in_waste_detected`: 배너 문자열이 `Result: WASTE DETECTED` → `## Result` + `wasteful span` 로 이동해서 assertion 업데이트.
- `test_readme_example_has_coverage_banner` · README `Result:` fenced 예제: 새 문면에 맞게 regex 와 예제 텍스트 동시 갱신.
- 사전등록 없이 진행된 변경이라 §3 예측 목록이 없었다. 다음부터 문면 변경 시 깨질 테스트를 먼저 열거한다.

### 릴리스 이유

pip-installed 사용자의 3-command 재현 시나리오 (`pip install clew-custos && ... && python -m clew analyze case.jsonl`) 가 정정된 배너를 보려면 새 배포가 필요하다. v0.4.0 이 이미 PyPI 에 있으므로 v0.4.1 로 올린다.

---

## 0.4.0 — 2026-08-01

### ★ Breaking

- **`Span` model gains an optional `raw_output_text` field** (`ce0996c`).
  `Span` still uses `ConfigDict(extra="forbid")`, so **an older version of `clew` cannot open a trace JSON that this version wrote.** This version still opens files produced by older versions (the new field defaults to `null`). The break is one-directional.

  Impact: if you `capture_to_file(...)` (or otherwise persist a `Trace` JSON) with 0.4.0 and then try to load that file with an older `clew` install, `load_trace(...)` raises `ValidationError`. Upgrade the reader to 0.4.0 or newer.

  Rationale: `raw_output_text` preserves the tool span's original response bytes so `id_bridge` extraction survives `preprocess_trace`'s `extract_output_text` step. Full context in `openinference_output_text_fix_PREREG.md` v3 §2.1 (local design doc).

### New features (user-visible)

- **OpenInference adapter — LangChain and CrewAI traces.** `ingest_from_otel_json` (SDK JSON array, Format A) and `ingest_from_openinference_json` (nested dict, Format C) both route to a common `ingest_otel_spans` path with `_agent_or_node_id_of` per-span-kind mapping and `_extract_tool_output` envelope shim (LangChain `{"type":"tool","data":{"content":…}}` unwrap; CrewAI `text/plain` raw). Full lineage recorded in `docs/OPENINFERENCE_ADAPTER_PREREG.md`.
- **`clew.yaml` — user tool registration (Phase 1).** Four categories: `read_only`, `side_effect`, `payload_dependent`, `declarative`. Discovery order: `--config` flag > walk-up from the trace file > `~/.clew/config.yaml`. Overrides against Clew's built-in mappings are logged to stderr rather than silently accepted.
- **`clew.yaml` — `entity_id` path registration (Phase 2).** `entity_id: response.ticket.id` (dot-path only; arrays, wildcards, and JSONPath rejected). `entity_id` is only valid on `category: side_effect`; suspicious tails (`request_id`, `session_id`, `correlation_id`, `transaction_id`, …) trigger a one-line stderr warning. Runtime extraction-failure ratios print per tool, with an envelope-prefix hint pointing at the framework path table when any failure is present.
- **Duplicate creation check report section.** A dedicated section under waste details lists side-effect tool pairs and classifies each as `differ` (two distinct entity IDs → real duplicate creation), `same` (same ID → likely idempotent), or `no_id` (extraction failed). The check is additive: `waste_span_ids`, `between_window_counts`, and the frozen 159/76/3197 Toolathlon distribution are bit-identical.
- **Tool mapping coverage banner** with the top 5 unrecognized tool names surfaced alongside the coverage percentage. The banner splits `built-in` vs `user-registered` when both are present, and carries an explicit footnote that precision bounds were measured on the built-in mappings only.
- **`between_window` — 5-value sub-classification of `idempotent`.** Report tells you *which evidence* supports the no-state-change reading: `declarative`, `no_side_effect`, `payload_dependent`, `targeted_writes`, `high_volume`. The 5 counts are frozen at `1,226 / 888 / 405 / 248 / 1,024` on the Toolathlon reference set.
- **`raw_output_text` safety net.** `id_bridge` extraction now reads `raw_output_text or output_text`, so a preprocessed `output_text` on the LangChain/OpenInference path no longer silently loses entity IDs. See the Breaking note above for schema impact.

### Documentation

- **README: entity_id path per framework table** (`2f15167`) with the four instrumentors measured against a dict-returning tool: LangChain / CrewAI / OpenAI Agents use `ticket.id`; LlamaIndex needs `raw_output.ticket.id` because its `FunctionTool` serializes returns as `{"blocks":[…], "raw_output":<orig>, …}`.
- **Tier 1 pre-registration and results published to `docs/`.** `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` and `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_RESULTS.md` land the judgment criteria and the resulting per-framework classification. Both the criteria and the results explicitly record §2.1 R2 (our non-empty `output.value` rule) as stricter than the OpenInference spec — the discrepancy is documented as a known adapter policy, not a spec claim.
- Clopper-Pearson labels standardized on **"95% two-sided (2.5% each tail)"** across all docs (`775883b`). Prior "90% CI" labels were incorrect; underlying numeric bounds were already correct.

### Honesty boundaries (existing rules, restated for the release)

- No "savings" or "confirmed waste" phrasing anywhere in report text or docs.
- Frameworks are listed by measured name only: **"OpenInference 계측 3 개 프레임워크에서 실측 확인 — LangChain, CrewAI, LlamaIndex."** OpenAI Agents SDK, Anthropic (direct SDK), and AutoGen are recorded separately as "current instrumentor cannot be read by 0.4.0" — the underlying SDKs are not evaluated.
- The phrase "여러 프레임워크" ("multiple frameworks") is banned, per `docs/OPENINFERENCE_FRAMEWORK_EXPANSION_PREREG.md` §4.1.
