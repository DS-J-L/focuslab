# FocusLab — Windows 집중 패턴 측정 앱 개발 계획

> 상태: Windows 오픈소스 개발 실행 계획 v1.0 · 기준일: 2026-10-20 · 진행 현황은 [README 로드맵](README.md#개발-로드맵) 참고\
> 대상: Windows 11 공식 개발·검증 우선, Windows 10은 별도 호환성 테스트; 개인 사용자·로컬 우선(계정·클라우드 불필요)\
> 범위: 웹캠 기반 행동 관찰 + PC 활동 기록 + 세션별 집중 패턴 분석 + 동의 기반 자동 활동 기록([§18](#18-v02-확장-native-windows-activity-tracking-engine))\
> 주의: ADHD 진단·치료·의료기기 기능을 제공하지 않음. '집중'을 카메라만으로 직접 측정할 수 없음.

## 0. 제품 미션, 경쟁 제품과의 차이점, 공개 원칙

**슬로건:** *Know your workflow, not just your screen time.*

**미션:** 사용자가 목표 작업에서 언제, 왜 벗어나는지 추적하고 자기 피드백을 통해 다시 복귀하기 쉬운 환경을 만드는 Windows 오픈소스 앱.

### 경쟁 제품과 차별화

- 화면을 바라보는 것만으로 `집중 중`이라고 단정하지 않는다. **현재 설정한 목표와 사용 중인 앱·사이트의 관련성**을 먼저 본다.
- 코딩·강의·종이책/필기 등 작업 모드를 제공하고, 고개를 숙였다는 이유만으로 딴짓이라고 판단하지 않는다.
- `왜 이탈로 추정했는지` 사용자에게 보여주고 즉시 정정 가능하게 한다. 정정은 사용자의 데이터에만 적용한다.
- 작업 유지율, 이탈 의심 시간, 복귀 시간, 판정 불가 시간의 **근거와 한계**를 보고한다.
- 클라우드·계정·상시 감시를 강제하지 않는다. 오프라인·로컬 우선, 소스 공개, 센서 모듈 교체 가능.

**네이밍 리스크:** `FocusLab`이라는 이름을 사용하는 다른 서비스들이 존재한다. 작업명으로 사용하되 공개 배포 전 GitHub 이름, 도메인, 상표의 충돌 여부를 다시 검토한다. 오픈소스 라이선스는 타인의 상표 사용 권한을 부여하지 않는다.

**플랫폼 원칙:** Windows 11 64비트를 개발·CI·릴리스 인증 대상으로 한다. Windows 10의 일반 지원은 2025-10-14에 종료되었으므로 공식 지원을 약속하지 않고 커뮤니티 베스트에포트로만 분리한다.

### 오픈소스 공개 원칙

- **저장소 공개:** 초기 PR-00부터 공개 저장소, Apache-2.0을 기본 후보로 채택. LICENSE, NOTICE, README, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, PRIVACY 문서 포함.
- **라이선스 검토:** 자체 작성 코드는 Apache-2.0으로 공개할 수 있지만 PySide6/Qt는 LGPLv3/GPLv3/상용 조건이 있으며 실제 재배포 방식을 점검한다. MediaPipe와 **모델 파일 각각**의 이용·재배포 라이선스를 따로 확인하고 THIRD_PARTY_NOTICES에 기재한다.
- **출처와 보안:** 의존성 고정, 모델 SHA256 체크섬, 타사 고지, SBOM 생성(가능하면), 보안 취약점 비공개 신고 경로 마련.
- **기여:** Good first issue, 작업별 PR, Windows 재현 절차, 영어/한국어 README 또는 번역 가이드.
- **브랜치 정책:** main 보호(테스트 통과 필수), 직접 push 대신 feature 브랜치 → PR → 검증 → 머지.

## 0-1. 한 문장 목표

사용자가 직접 시작한 공부/개발 세션 동안, 웹캠의 얼굴·머리 방향·자리 여부와 Windows 활성 프로그램·유휴 상태를 기록하고, (선택형 Chrome 확장 설치 시) 허용된 도메인 관련성을 결합해 **목표 관련 활동/잠재적 이탈/자리 비움/판단 불가**를 분리해 시각화하며, 사용자의 정정 피드백을 반영하는 오픈소스 로컬 데스크톱 앱을 만든다.

### 필수 원칙

1. 촬영은 사용자가 명시적으로 켠 세션에서만 시작한다. 끄면 즉시 카메라를 해제한다. 상시·몰래 촬영 금지.
2. 원본 영상·음성·키 입력 내용·스크린샷은 기본적으로 저장하지 않는다. 로컬 이벤트·집계값만 저장한다.
3. '시선이 화면 밖'은 **딴짓 확정**이 아니다. 카메라가 꺼져 있거나 가려진 상태는 `UNKNOWN`으로 처리한다.
4. 앱 자체가 학습을 방해하지 않도록 알림은 기본 비활성 또는 저빈도 설정, 휴식과 집중 모드를 구분한다.
5. 모든 감지 모델은 교체 가능한 인터페이스 뒤에 둔다. UI, 분석, 저장소를 느슨하게 결합한다.
6. 앱이 수집하는 내용·권한·보존 기간과 즉시 삭제 방법을 명확히 보여준다.

## 1. 제품 정의와 범위

### 대상 사용자 시나리오

- 사용자가 '알고리즘 문제 풀기'라는 목표를 선택하고 25분 세션을 시작한다.
- PC에서 VS Code, 강의, 공식 문서 등 작업 관련 앱을 허용 활동으로 지정한다.
- 웹캠은 눈/얼굴·머리 방향과 카메라 내 사람의 존재 여부를 추적한다.
- 웹캠·PC 이벤트를 결합해 1초 단위로 상태를 판단하되, 애매한 경우는 `UNKNOWN`으로 남긴다.
- 끝나면 작업 유지 시간, 작업 전환 수, 잠재적 이탈의 지속 시간, 자리 비움, 본인 수정 내역을 표시한다.
- 사용자가 '책을 보느라 아래를 봤음', '정상 작업이었음', '휴식이었음'을 정정한다.

### v0.1(MVP) 포함

- Windows 11 x64 단일 사용자 로컬 실행
- 세션 시작/일시정지/재개/종료, 목표/모드/허용 앱 설정
- 웹캠 미리보기, 카메라 선택, 얼굴 감지, 머리 방향 추정, 얼굴 없음/불확실 판정
- Windows 활성 프로그램, 창 전환, OS 유휴 시간 감지
- 이벤트 타임라인, 세션 요약, 간단한 일·주 리포트
- 온디바이스 처리, 영상 원본 미저장, 데이터 내보내기/삭제

### 브라우저 관련성 측정의 기술적 경계

- **기본 Windows 앱만 설치한 경우** 브라우저가 Chrome인지 정도를 알 뿐, 화면에 표시된 사이트가 공식 문서인지 SNS인지 확정할 수 없다.
- **추가 Chrome 확장을 설치·허용한 경우** 현재 활성 탭의 hostname만 PC 앱에 전달하여 사용자 설정 목표별 관련성을 분류할 수 있다. 전체 방문 기록/경로/검색어는 수집하지 않는다.
- 이 기능은 차별화의 핵심이지만 설치·통신 복잡도가 있어 PR-09로 분리한다. v0.1은 앱 단위 관찰의 제한을 명시한다.

### v0.2 포함

- 스마트폰 객체 감지(카메라 화면 내에 보일 때만), 사용 환경별 보정
- 독서/필기/코딩 모드별 규칙, 피드백을 반영하는 개인화
- 시스템 트레이, 알림 강도 제어, 자동 복구

### v1.0 포함

- 배포 가능한 Windows 설치 패키지, 설정 마이그레이션, 안정성 테스트
- 성능/오탐 지표 측정, 접근성, 고장 대응 및 진단 로그(민감 정보 제외)

### 명시적 제외

- ADHD 확률/의학적 진단 점수, 감정 인식, 얼굴 신원 식별
- 백그라운드 상시 녹화, 키로깅, 전체 화면 녹화, 타인 감시
- 클라우드 업로드/계정/다기기 동기화, 자동 유료 결제
- 스마트폰 화면의 실제 사용 내용 추적, 웹캠으로 화면상의 특정 픽셀 주시 좌표를 정밀 보장

## 2. 기술 결정

| 층       | 기술                                                    | 결정 이유                           |
| ------- | ----------------------------------------------------- | ------------------------------- |
| 언어·패키지  | Python 3.11, `uv`, `pyproject.toml`, 잠금 파일            | AI/Windows API 활용, 재현 가능한 개발 환경 |
| 데스크톱 UI | PySide6(Qt Widgets)                                   | 빠른 Windows MVP, 시스템 트레이, 스레드 분리 |
| 카메라     | OpenCV                                                | 웹캠 캡처/색공간 변환/프레임 조절             |
| 얼굴 특징점  | MediaPipe Tasks `FaceLandmarker`                      | 얼굴 랜드마크·얼굴 변환 행렬, 실시간 처리        |
| 휴대폰 감지  | MediaPipe Tasks `ObjectDetector` + 휴대폰 클래스가 있는 검증된 모델 | 추가 기능으로 도입, 탐지 성능 확인 필수         |
| PC 이벤트  | pywin32 + psutil                                      | Windows 포그라운드 창/프로세스와 사용자 유휴 시간 |
| 영구 저장소  | 내장 `sqlite3` (WAL 모드)                                 | 서버 불필요, 사용자가 삭제/이동 가능           |
| 테스트·품질  | pytest, pytest-qt, ruff, mypy 또는 pyright(점진적)         | 모듈·UI·규칙 테스트, 정적 검사             |
| 배포      | `pyside6-deploy`(Nuitka 기반) 우선 검증, 대안 PyInstaller     | Windows 실행 파일 생성, 실제 환경 패키징 확인  |
| CI      | GitHub Actions Windows runner                         | lint/test/build smoke 검증        |

**주의:** 패키지 버전은 PR-00에서 실제 Windows 환경의 호환성을 확인한 뒤 잠금 파일로 고정한다. MediaPipe용 `.task/.tflite` 모델은 실행 파일과 함께 패키징하고 배포·라이선스·해시를 관리한다.

### 시스템 환경 및 의존성 제한

- **Windows 11 x64**: 개발 및 주요 테스트 대상, Python 3.11 고정 후 확인한 패키지 버전은 `uv.lock`으로 잠금.
- **권한 요구:** 관리자 권한을 전제로 하지 않고 Windows 카메라 접근 권한이 없을 때 PC 기록만으로 폴백.
- **온디바이스 ML:** 얼굴/폰 객체 추론 자체는 네트워크 없이 동작. 첫 모델 설치/업데이트는 네트워크가 필요할 수 있어 실행 파일에 검증된 모델 포함.
- **오프라인 작동:** 모든 세션 저장과 보고서 생성은 인터넷 연결 없이 동작.

### 프로세스/스레드 경계

- **메인(UI) 스레드:** 화면 표시, 버튼, 설정 변경. 추론·카메라 캡처 실행 금지.
- **카메라 워커:** 장치 오픈/종료, 캡처, 최신 프레임 큐(크기 1\~2, 오래된 프레임 버림).
- **얼굴 추론 워커:** 적정 FPS(예: 5\~10)를 목표로 처리. 연산이 느리면 프레임 스킵.
- **스마트폰 감지 워커(v0.2):** 저빈도(예: 1\~2 FPS), 얼굴 추론과 자원 경쟁 측정.
- **PC 추적 워커:** 약 1초 주기 활성 앱·OS idle 시간 이벤트 발행.
- **판단/저장 워커:** 타임스탬프 기반 입력 병합 → 1초 상태·상태 변화 이벤트 → SQLite 저장.
- **UI 갱신:** 0.5\~1초 간격으로 요약 데이터만 화면에 반영.

### 전체 파이프라인

```
Webcam -> OpenCV CameraService -> FaceLandmarker -> FaceObservation --+
                                        PhoneDetector ------------(v0.2)--+
Windows foreground/idle -> ActivityTracker -> ActivityObservation -+->
        Sensor Fusion -> Mode-aware Rule Engine -> StateTransition -> SQLite
                                                               |
                                                  PySide6 Session UI / Reports
```

### 데이터 계약

상태(`FocusState`), 얼굴 관찰(`FaceObservation`: 얼굴 보임 여부·보정된 yaw/pitch·품질), PC 활동 관찰(`ActivityObservation`: 프로세스 이름·허용 앱 여부·유휴 시간·화면 잠금)의 정의는 [domain/models.py](src/focuslab/domain/models.py)가 기준이다. 관찰값이 없으면 `None`이며 이는 이탈의 증거가 아니라 판단 불가를 뜻한다.

- 센서 워커는 `Observation`만 발행하고 판단하지 않는다.
- `RuleEngine`은 관찰값+세션 모드+시간 창을 입력받아 상태와 근거 코드(`reason_codes`)를 반환한다.
- 저장에는 UTC 시각, 세션 내 단조 증가 타임스탬프, 분류기/규칙 버전, 신뢰도/판단 불가 사유를 남긴다.
- 영상·프레임·얼굴 좌표 원본의 장기 보관은 금지. 이벤트와 필요 최소 집계만 보관한다.

## 3. 코드 구조

패키지 구성은 [README 저장소 구조](README.md#저장소-구조)에 정리되어 있다. 후속 기능은 같은 경계를 따른다: 휴대폰 감지(PR-10)는 `camera/`에 센서로 추가하고, Chrome 확장 연동(PR-09)은 관찰값만 발행하는 별도 활동 소스로 붙인다. 테스트 데이터는 합성 이벤트(`focuslab.mock_sources`)가 기본이며 실제 영상은 동의 없이 커밋하지 않는다.

## 4. 데이터 모델

스키마의 기준은 [storage/migrations.py](src/focuslab/storage/migrations.py)이다.

- **session** (`id`, `goal`, `mode`, `planned_minutes`, `started_at_utc`, `ended_at_utc`, `status`, `camera_enabled`, `rule_version`, `paused_seconds`, `self_report`)
- **session_allowed_app** (`session_id`, `process_name`, `display_label`)
- **state_sample** (`session_id`, `second_offset`, `state`, `confidence`, `reason_codes`, `app_name`) — 1초 단위
- **event** (`id`, `session_id`, `started_offset_ms`, `ended_offset_ms`, `type`, `severity`, `reason_codes`, `app_names`, `source`) — 같은 상태가 이어진 구간
- **feedback** (`id`, `event_id`, `corrected_label`, `comment`, `created_at_utc`) — 구간당 정정 1개
- **settings** (`key`, `value`, `updated_at_utc`)
- **migration** (`version`, `applied_at_utc`)

기본 저장 폴더는 `%LOCALAPPDATA%\FocusLab`(로밍하지 않는 로컬 앱 데이터)이며 `--data-dir`/`FOCUSLAB_DATA_DIR`로 바꿀 수 있다. SQLite foreign key 활성화, WAL 및 트랜잭션·마이그레이션 테스트를 수행한다. 개인정보 처리 기본값은 로컬 전용, 카메라 미리보기만 메모리에 유지, 데이터 보존 기간 설정 및 전체 삭제를 지원한다.

## 5. 동작 상태와 판정 규칙

### 세션 모드

- `CODING`: IDE/공식 문서/허용 브라우저 작업 중심. 화면 밖 시선만으로 이탈 확정 금지.
- `LECTURE`: 동영상 재생·화면 응시 중심. 마우스/키보드 입력이 없어도 정상 가능.
- `READING_WRITING`: 책/필기 가능. 아래쪽 시선 허용 범위를 넓게 잡음.
- `CUSTOM`: 허용 프로그램·기준 개인 설정.

### 초기 규칙(튜닝 전 가설, 의학적 기준 아님)

| 입력 조건                  | 초기 처리               | 예외/안전장치                  |
| ---------------------- | ------------------- | ------------------------ |
| 센서 오류/카메라 차단/얼굴 가림     | `UNKNOWN`           | 자리를 비웠다고 단정 금지           |
| 얼굴 없음 20초 지속 + PC idle | `AWAY` 가능성          | 모니터 밖에서 책 읽는 모드는 다르게 처리  |
| 얼굴 방향 15초 이상 이탈 + 무관 앱 | `POSSIBLY_OFF_TASK` | 아래쪽 시선만으로 판정 금지          |
| 무관 앱 활성 15초 이상         | `POSSIBLY_OFF_TASK` | 허용 앱 목록·공식 문서 예외 적용      |
| 허용 앱 활성 + 얼굴 관찰 정상     | `ON_TASK` 추정        | 학습 수행 자체/집중력을 확정하는 의미 아님 |
| 사용자가 휴식 버튼             | `BREAK`             | 통계에서 휴식으로 분리             |
| 휴대폰 화면 내 검출(v0.2)      | '휴대폰 관찰됨' 이벤트       | 휴대폰 존재만으로 딴짓 확정 금지       |

- 상태 변경에 **히스테리시스**(진입/이탈 기준 차등)와 최소 지속 시간을 사용해 깜박임 방지.
- 정상 활동인데 의심 이벤트가 발생하면 사용자가 즉시 정정 가능.
- 카메라 미사용 세션도 PC 활동 기반으로 정상 동작해야 한다.
- 시스템 잠금/절전/세션 중단 시 사용자에게 복구를 묻고 실제 관측 불가능 구간은 `UNKNOWN` 처리.

## 6. 집중 측정 지표 정의

`집중 점수` 같은 의학적·심리적 개념을 과도하게 수치화하지 않는다. 기본 지표는 **관찰된 작업 관련 활동 시간**이다.

- **세션 총 길이:** `종료 - 시작` (일시정지 제외 여부를 명확히 표시).
- **작업 관련 추정 시간:** `ON_TASK` 구간의 누적 시간. 실제 집중의 증명은 아님.
- **이탈 의심 시간:** `POSSIBLY_OFF_TASK` 구간의 누적 시간.
- **자리 비움:** `AWAY` 상태 시간 별도 표기.
- **측정 불가:** `UNKNOWN` 시간, 비율을 따로 표기. 카메라가 꺼졌을 때 낮은 점수로 취급하지 않음.
- **작업 관련 활동 비율:** `ON_TASK / (ON_TASK + POSSIBLY_OFF_TASK)` (분모가 0이면 `측정 불가`). `AWAY`, `BREAK`, `UNKNOWN`은 분리해 보여주므로 지표가 과장되지 않게 측정 커버리지 동시 표시.
- **복귀 시간:** `POSSIBLY_OFF_TASK` 이벤트 종료에서 다음 `ON_TASK` 시작까지의 시간. 세션 중단/휴식으로 끝난 경우 `복귀 기록 없음`으로 남김.
- **근거 설명:** 관측 기여 요소(PC 앱, 모드, 시선 품질 등)와 룰 버전을 표시. 1초 단위 추론은 신뢰도가 낮으면 `UNKNOWN` 우선.

## 7. PR 단위 개발 로드맵

각 PR은 하나의 목적만 수행한다. **기능 구현 → 자동 테스트 → Windows 실제 검증 → PR 리뷰 → 머지** 후 다음 단계로 진행한다. PR이 실패하면 후속 단계 시작 전에 복구한다.

| PR        | 제목                                            | 구현 범위                                                                                   | 필수 완료 조건                                            |
| --------- | --------------------------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **PR-00** | `chore: open-source bootstrap`                | 공개 저장소, Apache-2.0 라이선스 초안, README/SECURITY/CONTRIBUTING/PRIVACY/CI, `uv`·PySide6·모의 센서 | 다른 Windows 11 PC에서 설치/테스트/빈 UI 실행 성공; 라이선스 검토 이슈 생성 |
| **PR-01** | `feat: session lifecycle and SQLite`          | 시작/일시정지/재개/종료, 데이터 스키마/마이그레이션                                                           | 세션 상태 전이·강제 종료 복구 테스트 통과                            |
| **PR-02** | `feat: camera capture`                        | 카메라 선택, 미리보기, 권한 오류, worker 해제                                                          | 카메라 켜기·끄기·장치 분리 복구, 영상 저장 없음                        |
| **PR-03** | `feat: face landmark tracking`                | MediaPipe Tasks, 랜드마크, 얼굴 감지 여부/추론 품질                                                   | 10분 동작, UI 멈춤 없음, 모델 오류 시 PC 전용 모드 유지               |
| **PR-04** | `feat: head pose and calibration`             | 머리 방향, 정면 보정, UNKNOWN 처리                                                                | 좌우/아래쪽 자세 반복 측정·개인 보정 동작                            |
| **PR-05** | `feat: windows activity tracking`             | 포그라운드 앱, idle, 앱 화이트리스트/블랙리스트                                                           | 작업 앱 전환·idle·잠금/절전 처리 확인, 민감한 창 제목 저장 금지            |
| **PR-06** | `feat: task-context state engine`             | 모드별 허용 앱, 상태 머신, 근거 코드, 타임아웃/히스테리시스                                                     | 최소 25개 합성 이벤트 테스트, 카메라 OFF에서도 동작                    |
| **PR-07** | `feat: live session dashboard`                | 홈·세션·타임라인·센서 상태·세션 제어                                                                   | 25분 실측 세션 완료, 트레이 최소화 기록 지속                         |
| **PR-08** | `feat: reports and data privacy controls`     | 일별/세션별 통계, 수동 정정, 데이터 삭제/CSV/JSON 내보내기                                                  | 상태 합산 정확성, 삭제 테스트 → **v0.1 MVP**                    |
| **PR-09** | `feat: optional Chrome extension`             | 명시적 동의를 받은 현재 활성 탭의 도메인만 Windows 앱에 전달; MV3 + Native Messaging                          | 설치/해제, 차단/시크릿 모드, 메시지 인증/스키마·최소권한 테스트               |
| **PR-10** | `feat: optional phone detection`              | 검증된 모델로 카메라 화면에 보이는 휴대폰 탐지                                                              | OFF/ON 독립 실행, 오탐/미탐 기록, 영상 유출 없음                    |
| **PR-11** | `feat: personalized feedback and quiet coach` | 작업 모드별 판단 보정, 사용자 정정 반영, 알림 쿨다운                                                         | 사용자 정정이 반영되고 알림이 과잉 발송되지 않음 → **v0.2 Beta**         |
| **PR-12** | `test: field validation and robustness`       | 실제 사용 라벨 검증, 센서 오류, 장시간 실행, 리소스 테스트                                                     | 신뢰도·성능 보고서, 새 Windows 계정/환경 E2E 테스트 통과              |
| **PR-13** | `release: Windows open-source distribution`   | 모델 고지/의존성 감사, Nuitka 빌드, 설치/제거, 릴리스, docs                                               | Python 없는 Windows 11에서 설치/실행/제거 성공 → **v1.0**       |

### 단계별 상세 구현 포인트

**PR-00**: `python -m focuslab` 혹은 `uv run focuslab` 진입점부터 준비한다. 버전 고정/문서/코딩 컨벤션, 모든 이벤트 타입을 정의하고 센서가 없어도 `MockFaceSource`와 `MockActivitySource`로 UI 테스트가 가능하게 한다.

**PR-01**: `IDLE -> RUNNING -> PAUSED -> RUNNING -> FINISHED`를 명시적으로 구현한다. 프로그램이 비정상 종료되면 재시작 시 마지막 세션을 복구하거나 중단 처리한다.

**PR-02\~04**: 렌더링과 추론을 서로 다른 워커에서 수행한다. 화면에 랜드마크 표시를 켜고 끌 수 있도록 하고, 기본 저장은 이벤트 메타데이터만 저장한다. 최초 보정 안내(정면·좌측·우측·아래쪽)를 제공한다.

**PR-05**: 브라우저 탭별 URL은 운영체제 활성 창 추적만으로 정확히 얻을 수 없다. v0.1에서는 브라우저 프로세스 수준만 분석하고, 도메인 추적이 필요하면 별도의 최소 권한 Chrome 확장 프로그램을 후속 과제로 설계한다.

**PR-06**: 매 1초 데이터를 평가하되, 결측값에 대해 이전 값을 무한 유지하지 않는다. 각 관찰에 TTL(유효 기간)을 설정하고 만료되면 `UNKNOWN`으로 처리한다. 실제 집중도 0\~100% 같은 표현보다 '목표 관련 활동 추정 비율'을 표시한다.

**PR-07\~08**: 홈/실시간 세션/세션 상세/설정 4개 화면으로 충분하다. 그래프는 전환 횟수와 상태 지속 시간 중심으로, '정정하기'가 접근하기 쉬운 위치에 있어야 한다.

**PR-09**: Chrome MV3 확장 프로그램은 사용자 선택 시에만 켠다. **방문 기록 전체와 URL 경로는 수집하지 않고 활성 탭 hostname만 전달**한다. 통신은 Chrome Native Messaging을 원칙으로 해 로컬 HTTP 서버 노출을 피한다. Windows 등록/설치 경로, 허용 origin, 메시지 검증, 종료 처리, 시크릿 모드 제외를 테스트한다. 확장이 설치되지 않으면 `브라우저 세부 활동 미확인`으로 표시한다.

**PR-10**: 모델이 휴대폰(`cell phone` 등) 클래스를 지원하는지 명시적으로 검증한다. 손에 든 물체가 가려지거나 화면 밖에 있으면 추측하지 않는다. 카메라 영상에서 휴대폰 발견은 곧 사용 증거가 아니다.

**PR-11**: 알림을 기본 OFF 또는 최소화하고, 일정 시간 내 같은 원인 알림 재발행 금지(쿨다운), 휴식·시험·강의 모드에서는 제한한다.

**PR-12\~13**: 모델 데이터와 라이선스를 함께 묶고, Windows 사용자 계정/권한별 카메라 접근 문제를 확인한다. 릴리스 파일은 체크섬과 변경 로그를 첨부한다.

## 8. 화면 요구사항

1. **Home**: 오늘의 세션·작업 유지 시간, [집중 시작] 버튼, 빠른 모드 선택.
2. **Live Session**: 남은 시간/목표, 카메라 상태 표시, 포그라운드 앱, 현재 분류(`ON_TASK` 등), [일시정지/종료], [잘못된 판정 수정].
3. **Session Report**: 구간별 상태 타임라인, 작업 앱 전환, 이탈 의심 이벤트별 이유, 정정 내역, 목표 달성 여부(자기보고).
4. **Settings**: 카메라 선택, 촬영 안내/동의, 감지 활성화 스위치, 보정, 모드·허용 앱, 알림 수준, 보존 기간, 데이터 내보내기/삭제.

UI 문구는 '집중 87점', 'ADHD 위험' 대신 '작업 유지율(추정)', '화면 외 방향 관찰', '판단 불가'로 작성한다.

## 9. 테스트와 품질 게이트

### 실험의 근거와 정확도 측정

- 10\~20개 세션을 **본인이 수동 라벨링한 기준 로그**와 비교한다. 원본 영상 저장은 하지 않는 것이 기본이며 테스트 데이터셋은 별도 동의 하에 합성·녹화된 공개/테스트 자료로만 만든다.
- 얼굴 없음/자리 이탈, 앱 전환, 실제로 수정한 이탈 구간을 따로 평가한다. `집중력 95% 정확도` 같은 과장 금지.
- **precision·recall, false alarms per hour, UNKNOWN 비율**, 센서별 커버리지, 배터리·CPU·메모리 데이터를 보고한다.
- 모델/규칙 보정 후 동일 테스트를 반복하고 기준 대비 개선 여부 확인. 사용자 진단 자료나 ADHD 점수로 활용하지 않는다.

### 필수 자동 테스트

- 단위: 세션 상태 전이, 시간 합산, 모드별 규칙, TTL 만료, 애매한 입력의 `UNKNOWN`, 중복 이벤트 제거.
- 통합: 모의 카메라/PC 이벤트 → 센서 융합 → SQLite 저장 → 리포트 계산 수치 일치.
- GUI: 실행/일시정지/재개/종료, 카메라 거부/장치 분리/오류, 종료 후 워커 잔류 없음.
- 회귀: 영상 저장 없음, 권한 미승인 시 측정 시작 안 됨, 비밀번호/키보드 내용 수집 없음.

### 실제 검증 프로토콜

자기 자신이 의도적으로 레이블을 붙인 10\~20개의 세션에서 다음 시나리오를 반복한다: (1) 코딩 10분, (2) 화면 강의, (3) 종이책/필기, (4) 잠깐 스마트폰 확인, (5) 자리 비움, (6) 웹캠 가림/불 꺼짐, (7) 앱 최소화, (8) Windows 화면 잠금, (9) 절전/복귀, (10) 웹캠 장치 분리.

비교 단위는 '딴짓'의 추상적 정답보다 **자리 이탈**, **활성 앱 전환**, **사용자가 직접 표시한 이탈 구간** 같은 관찰 가능한 이벤트로 한다. 실제 사용자 레이블 없이 정확도 수치를 주장하지 않는다.

### 목표 성능(최초 목표값, 하드웨어에 따라 수정)

- Windows 보급형 노트북에서 25분 세션 동안 앱 UI 정지/크래시 0건.
- 카메라+얼굴 추론 활성화 시 CPU 사용량·메모리 소비 측정, 과부하 시 자동 샘플링 저하.
- 카메라 사용 종료 후 OS 장치 핸들 해제 확인.
- 과도한 알림 방지: 사용자에게 표시되는 거짓 경고를 세션당 낮은 수준으로 제한(예: 30분당 1회 이하 목표). 검증 후 조정.
- 사용자 라벨과 비교해 `AWAY` / `POSSIBLY_OFF_TASK` 분류의 precision/recall을 분리 보고. 성능 목표는 베이스라인 측정 후 확정.
- 앱 재시작 시 DB 손상/세션 데이터 유실이 없어야 하며, 마이그레이션은 테스트된 백업·복구 경로를 가진다.

## 10. 보안·프라이버시 기준

- 카메라 시작 전 명확한 동의, 촬영 중 화면 및 트레이에서 가시적인 상태 표시. 최초 실행 시 카메라·PC 정보·확장 도메인 수집 동의를 각각 구분한다.
- 영상/음성/스크린샷/키보드 입력 내용/브라우저 전체 방문기록을 기본 수집하지 않음.
- 프레임은 메모리에만 존재하고 녹화·업로드 기능을 구현하지 않음.
- 앱 종료, 일시정지, 카메라 끄기 때 장치·워커 즉시 해제.
- 민감한 창 제목·문서 제목은 기본 저장 금지, 앱 이름 정도로 제한.
- 디버깅 로그는 사용자의 개인정보·얼굴 좌표·URL·원시 영상을 포함하지 않음.
- 로컬 데이터 내보내기/삭제와 유효 기간 설정 지원.
- 앱의 모든 평가 결과가 의료적 의미를 지닌다고 주장하지 않음.
- **자신의 행동 분석 용도만 지원하며 동의 없는 타인 모니터링/원격 감시 기능을 도입하지 않음.**
- Chrome Native Messaging host는 로컬 앱과 확장 연결 시 origin allowlist, 메시지 길이 제한, 입력 유효성 검사 적용.

## 11. 릴리스 완료 정의(DoD)

**MVP=v0.1:**

- 처음 설치 후 사용자가 카메라/목표/모드를 선택할 수 있다.
- 25분 세션을 안정적으로 실행하고 최소화해도 기록된다.
- 얼굴 보임/불확실/자리 이탈, 활성 앱, 유휴 상태를 구분한다.
- 세션 타임라인 및 사건 근거를 확인하고 사용자가 분류를 수정할 수 있다.
- 영상 원본은 저장되지 않으며, 전체 기록을 내보내거나 삭제할 수 있다.
- 카메라가 없어도 앱이 종료되지 않고 PC 기반 세션이 진행된다.

**v1.0:**

- 휴대폰 감지는 선택형이고 불확실성을 정확하게 표현한다.
- 알림·모드·보정 개인화가 가능하다.
- 10\~20개 검증 세션 보고서에 오탐/미탐·한계가 정리되어 있다.
- 새 Windows PC에 Python 설치 없이 설치·실행·제거 가능하다.
- CI green, 태그/변경 로그/설치 가이드/개인정보 설명 문서가 있다.

## 12. 추천 일정(주당 10\~15시간 작업하는 1인 기준의 가안)

| 주차  | 우선 PR     | 결과                             |
| --- | --------- | ------------------------------ |
| 1주차 | PR-00\~02 | 공개 저장소/세션/카메라                  |
| 2주차 | PR-03\~04 | 얼굴 추적과 보정                      |
| 3주차 | PR-05\~06 | Windows 활동 및 목표별 판단 엔진         |
| 4주차 | PR-07\~08 | v0.1: 대시보드/데이터 관리·실사용 MVP      |
| 5주차 | PR-09     | 선택형 Chrome 확장과 통신 방식 검증        |
| 6주차 | PR-10\~11 | 휴대폰 감지/피드백·알림 v0.2             |
| 7주차 | PR-12     | 필드 검증·성능·장애 대응                 |
| 8주차 | PR-13     | Apache/Qt/모델 라이선스 점검·설치파일·v1.0 |

일정은 1인 개발 주당 10\~15시간 가정의 계획값이다. Chrome Native Messaging 설치, MediaPipe 패키징, 웹캠 하드웨어 변동, 오탐 문제에 따라 8주 이상 걸릴 수 있다. 진도는 날짜보다 PR 완료 기준으로 관리한다.

## 13. 개발 프로세스 및 PR 템플릿

브랜치 `main`은 항상 실행 가능 상태를 유지한다. 각 PR마다 다음을 준수한다.

1. `feat/<scope>` 또는 `fix/<scope>` 브랜치 생성.
2. 계획 범위의 파일만 변경하고, UI/엔진 사이 데이터 계약을 지킨다.
3. unit/integration 테스트 및 lint 실행; Windows 실기기 검증이 필요한 경우 결과를 기록한다.
4. PR에 `목적 / 변경 / 테스트 / 제약 / 스크린샷(원본 카메라 영상 제외) / 다음 단계`를 기재한다.
5. CI 통과 + 기능 확인 후 머지; 다음 PR 착수. 미완성 기능은 비활성 feature flag로 숨긴다.

PR 본문은 [PR 템플릿](.github/PULL_REQUEST_TEMPLATE.md)을 따른다.

## 14. 개발 환경

환경 구성과 검사 명령은 [CONTRIBUTING.md](CONTRIBUTING.md)를 따른다. 의존성 버전은 `uv.lock`으로 고정되어 있으며, 새 의존성은 Windows Python 3.11에서 확인한 뒤 잠금 파일과 [제3자 고지](THIRD_PARTY_NOTICES.md)를 함께 갱신한다.

## 15. 미래 확장(별도 PR 제안, MVP에 넣지 않음)

- Chrome 확장 프로그램의 고급 분류(문서/강의/소셜 사이트, 사전 설정된 규칙을 사용자가 수정): PR-09에서는 도메인 최소 수집부터 시작.
- 선택형 로컬 LLM 리포트: 숫자로 설명 가능한 패턴 요약, 의료 주장·과잉 해석 금지.
- 웨어러블 수면/활동 데이터 연동(별도 동의/지원 확인).
- 상호작용 분석 고도화: 창 전환/휴식/세션 목표 달성으로 사용자 경험 개선.

## 16. 공개 저장소 문서와 기여 흐름

공개 저장소 필수 문서(LICENSE, NOTICE, THIRD_PARTY_NOTICES, README, PRIVACY, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT, 이슈·PR 템플릿, CI)는 PR-00에서 갖췄다. 기여 절차는 [CONTRIBUTING.md](CONTRIBUTING.md)를 따른다.

**릴리스 프로세스:** `v0.1.0` 로컬 MVP → `v0.2.0` 브라우저/폰/코칭 → `v1.0.0` 검증된 Windows 설치 배포. SHA256 체크섬, SBOM(가능하면), CHANGELOG, 제3자 고지 동봉. 자동 업데이트는 기본 OFF/별도 설계.

### 착수 전 체크리스트

- FocusLab 이름 사용 검토(동명 소프트웨어/상표/도메인). 불가하면 코드 패키지 이름을 유지하고 공개 제품명 변경 가능하게 리소스 분리.
- Windows 11 개발 환경과 USB/노트북 웹캠 준비.
- 관리자 권한 불필요한 카메라/활성 앱 샘플 코드 동작 확인.
- PySide6/Qt 배포 방식과 MediaPipe `.task/.tflite` 모델 라이선스·재배포 정책 기록.
- 동의 없이 로그·원본 영상·민감한 창 제목·URL 경로 업로드하지 않는 테스트 확보.
- '모든 행동을 집중/딴짓으로 확정하지 않고 UNKNOWN을 제공'하는 UI 원칙 동의.

## 17. 공식 참고 문서

- MediaPipe Face Landmarker Python: [https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python)
- MediaPipe Object Detector Python: [https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector/python](https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector/python)
- Qt/PySide6 배포: [https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
- Windows GetForegroundWindow: [https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getforegroundwindow)
- Windows GetLastInputInfo: [https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)
- Windows 10 지원 종료: [https://learn.microsoft.com/ko-kr/lifecycle/announcements/windows-10-end-of-support](https://learn.microsoft.com/ko-kr/lifecycle/announcements/windows-10-end-of-support)
- Qt for Python 라이선스: [https://doc.qt.io/qtforpython-6/](https://doc.qt.io/qtforpython-6/)
- Apache-2.0: [https://choosealicense.com/licenses/apache-2.0/](https://choosealicense.com/licenses/apache-2.0/)
- GitHub 커뮤니티 파일: [https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)

## 18. v0.2 확장: Native Windows Activity Tracking Engine

> 변경 기준일: 2026-10-20 · 현황 분석과 상세 설계: [docs/activity-engine.md](docs/activity-engine.md)

### 계획 변경 사항

- **관찰 범위 확장:** 기존 원칙 "사용자가 직접 시작한 세션에서만 관찰"에 더해, 최초 실행 시 **명시적 동의**를 받으면
  PC 활동(맨 앞 프로그램·유휴·잠금·절전)과 선택형 브라우저 도메인을 **백그라운드에서 자동 기록**한다.
  동의하지 않거나 기록을 일시정지하면 OS·브라우저 정보를 읽거나 쓰지 않는다.
- **카메라 원칙은 유지:** 카메라는 여전히 사용자가 켠 수동 집중 세션에서만 동작한다(상시 촬영 금지).
  자동 기록과 결합할 때는 같은 시간대의 세션 판정(자리 비움·화면 외 방향 등)을 겹쳐 보여줄 뿐 단정하지 않는다.
- **ActivityWatch 비의존:** 수집기·저장소·분류·대시보드는 FocusLab 자체 구현이다. ActivityWatch의 공개 기능 구성만
  참고했고 소스 코드는 사용하지 않는다.
- **PR-09(Chrome 확장)** 는 아래 PR-C로 대체하며 Microsoft Edge도 지원한다.
- 휴대폰 감지(PR-10)와 눈 감김 관찰은 이번 확장 범위에서 제외하고 기존 계획대로 후속 PR에서 다룬다.

### 추가 PR (PR-08 이후, 앞 PR 브랜치 기준으로 순차 머지)

| PR | 제목 | 범위 | 완료 조건 |
| --- | --- | --- | --- |
| **PR-A** | `feat: native Windows activity collector` | 스키마 v2, Win32 프로브, `ActivityRecorder`, 포그라운드 이벤트 훅 | 앱 전환·병합·저장 단위 테스트, 실기기에서 구간 기록 확인 |
| **PR-B** | `feat: idle and system event tracking` | 유휴 소급, 잠금·절전·로그오프·시계 변경, 비정상 종료 복구, 시작 프로그램, 트레이 상주, 최초 실행 동의 | 절전 시간 미계산, 강제 종료 후 데이터 무손상 |
| **PR-C** | `feat: native browser tracker` | MV3 확장(Chrome·Edge), Native Messaging host, 등록·해제, 검증·중복 처리 | 확장 없는 PC에서도 앱 추적 정상, 비공개 창 미수집 |
| **PR-D** | `feat: activity classification engine` | 10개 카테고리 규칙 분류, 신뢰도·근거·출처, 사용자 정정 반영, 제외 목록 | 모호한 사이트는 `Unknown`, 정정이 이후 분류에 반영 |
| **PR-E** | `feat: automatic session engine` | 자동 세션 감지·저장, 수동 세션·규칙 엔진·카메라 결과와 통합 | 유휴·작업 전환으로 분리, 수동 세션과 중복 집계 없음 |
| **PR-F** | `feat: activity dashboard` | 오늘 개요, 활동 타임라인, 일·주·월 통계 | 합계가 실제 경과 시간을 넘지 않음 |
| **PR-G** | `chore: activity stability, privacy and release checks` | 보존·내보내기·삭제, 성능 측정, 문서·CI | 장시간 실행 리소스 측정 결과 문서화 |
