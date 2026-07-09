> ### MuggleBlocker
> GDGOC on HUFS 25-26 summer vacation project

---

# 🧙‍♂️ MuggleBlockerDetector (AI 모듈) 사용 설명서
## 1. 모듈 초기화 (Pipeline 시작 부분)
UI나 메인 파이프라인이 켜질 때 딱 한 번만 객체를 생성해 주시면 됩니다.

``` Python
from ai_detector import MuggleBlockerDetector
# 객체 생성
detector = MuggleBlockerDetector()
```
## 2. 프레임 입력 (Input - 카메라 루프 내부)
카메라에서 읽어온 원본 프레임과 타임스탬프(밀리초)를 매 프레임 던져주시면, AI가 백그라운드에서 알아서 최적화된 비동기 분석과 스레드 신원 검증을 진행합니다.
``` Python
timestamp_ms = int(time.time() * 1000)
detector.process_frame(frame, timestamp_ms)
```
## 3. 상태 및 데이터 가져오기 (Output - UI 업데이트용)
매 프레임 process_frame 직후에 아래 메서드들을 호출하여 반환된 값으로 UI(경고화면, 박스 그리기 등)를 업데이트해 주시면 됩니다.

- `get_status() -> str`: 현재 보안 상태 반환 `("NORMAL", "AWAY", "INTRUSION")`

- `get_bbox() -> list`: 화면을 응시 중인 사람들의 얼굴 좌표 반환 `[[x, y, w, h], ...]`

- `get_cropped_box() -> list`: AI가 집중 추적 중인 ROI 영역 좌표 반환 [x1, x2, y1, y2] (전체 화면 감지 중일 때는 `None` 반환)

## 4. 🧠 핵심 로직: 상태(Status)가 결정되는 조건
모듈 내부에서 카메라 프레임을 분석하여 아래의 조건에 따라 보안 상태를 자동으로 판단합니다. 메인 파이프라인에서는 get_status() 결과값만 받아 UI를 전환해 주시면 됩니다.

### 🟢 NORMAL (안전)

조건: 화면을 응시하는 얼굴이 딱 1명일 때.

숨겨진 마법(스레드): NORMAL 상태가 유지되는 동안, 화면 렌더링에 렉(Lag)을 주지 않기 위해 백그라운드 스레드에서 **1분마다 한 번씩 '진짜 주인인지' 신원 검문(얼굴 인식)** 을 조용히 진행합니다.

### 🟡 AWAY (자리 비움)

조건: 화면을 응시하는 사람이 아무도 없을 때.

잠깐 고개를 돌리거나 기지개를 켜는 것에 반응하지 않도록, 얼굴이 30프레임 이상 연속으로 안 보일 때만 AWAY 상태로 전환됩니다.

### 🔴 INTRUSION (침입 감지 / 방어막 가동)

**[조건 1]** (어깨너머 훔쳐보기): 화면을 쳐다보는 사람이 2명 이상일 때. (오작동 방지를 위해 3초 이상 지속 시 확정)

**[조건 2]** (주인이 아님): 1분 주기로 도는 신원 검문 스레드에서 **'주인이 아닌 낯선 사람(머글)'**이 노트북을 하고 있다고 판별될 경우 즉시 전환됩니다.
