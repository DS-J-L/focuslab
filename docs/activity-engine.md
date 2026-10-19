# Native Windows Activity Tracking Engine — 현황 분석과 설계

> 기준: `feat/v0.1-prototype` (07bc83a) · 작성일 2026-10-20 · 관련 계획: [DEVELOPMENT_PLAN.md §18](../DEVELOPMENT_PLAN.md#18-v02-확장-native-windows-activity-tracking-engine)
>
> 목표: 사용자가 최초 설정에서 동의하면, 이후 타이머를 켜거나 활동을 입력하지 않아도 PC·브라우저 활동이
> 자동으로 기록·분류·분석되게 한다. ActivityWatch의 실행·API·DB·watcher에 의존하지 않는다.

## 1. 현재 저장소 분석 (v0.1 프로토타입)

| 영역 | 현재 구현 | 판단 |
| --- | --- | --- |
| 아키텍처 | `domain`(계약) → 센서(`activity`, `camera`) → `focus`(융합·규칙·지표) → `storage`(SQLite) → `services`(세션·워커·내보내기) → `ui`(PySide6). 센서는 관찰값만 발행 | **재사용**. 새 엔진도 같은 경계를 따른다 |
| Windows 활동 추적 | `activity/windows_tracker.py`: `GetForegroundWindow`→PID→psutil 프로세스 이름, `OpenInputDesktop`으로 잠금 감지, `visible_window_apps()`. **세션 tick(1초)에서만** 호출되는 폴링, 창 제목 미수집 | 함수는 **재사용**. 상시 기록·이벤트 훅·실행 파일 식별·접근 거부 처리·UWP 처리는 **신규** |
| 유휴 감지 | `activity/idle_monitor.py`: `GetLastInputInfo` + `GetTickCount` 랩어라운드 처리 | **재사용** (그대로) |
| 웹캠 분석 | `camera/*`, `services/worker_manager.py`: 캡처·추론 분리 스레드, 얼굴 보임·머리 방향·품질, 보정. 수동 세션 중에만 켜짐 | **재사용**. 상시 촬영은 하지 않는다(기존 원칙 유지). 눈 감김·휴대폰 감지는 미구현 |
| 집중 판단 엔진 | `focus/fusion.py`(TTL 융합), `focus/rules.py`(모드별 규칙·히스테리시스·근거 코드), `focus/metrics.py` | **재사용**. 브라우저 도메인을 알면 `BROWSER_DETAIL_UNKNOWN` 근거를 붙이지 않도록 확장 |
| 세션 관리 | `services/session_service.py`: 수동 세션 수명주기, 1초 샘플·구간 저장, 절전 공백 `UNKNOWN`, 크래시 시 `INTERRUPTED` 복구 | **재사용**. 자동 세션은 별도 엔진·테이블로 구분 |
| SQLite | `storage/migrations.py` 버전형 마이그레이션(v1), WAL, foreign key, `Repository` | **재사용**. 새 테이블은 마이그레이션 v2+로 추가, 기존 데이터 무손실 |
| 대시보드 | 홈(오늘 카드)·세션·리포트(7일 차트, 세션 타임라인, 정정)·설정. `StatCard`, `TimelineWidget`, `WeekChart` | 위젯 **재사용·일반화**, 활동 화면 **신규** |
| 트레이·백그라운드 | `ui/tray.py`: 세션 진행 중일 때만 창 닫기 → 트레이. 단일 인스턴스 `QLockFile` | **확장**: 상시 상주, 기록 일시정지/재개, 카메라 즉시 끄기 |
| 시작 프로그램 등록 | 없음 | **신규** (HKCU `Run`) |
| 브라우저 확장 | 없음 (PR-09 계획만 존재) | **신규** (MV3 + Native Messaging) |
| 테스트·CI | pytest 93개(단위·통합·오프스크린 GUI), ruff, Windows runner CI, `uv build` | **재사용**. 확장 프로그램 JS 테스트(node) 추가 |

중복 개발하지 않는 것: 유휴 시간 계산, 잠금 감지, 프로세스 이름 조회, 마이그레이션 러너, 동의 대화상자 형식,
내보내기 형식, 위젯, 카메라 파이프라인, 규칙 엔진.

## 2. 변경된 아키텍처

```
                       ┌──────────── focuslab 프로세스 ────────────────────────────────┐
 SetWinEventHook ─┐    │  activity/win_events.py  (메시지 전용 창 스레드)              │
 WTS 세션 알림  ───┼──▶ │    EVENT_SYSTEM_FOREGROUND, WM_WTSSESSION_CHANGE,             │
 전원·디스플레이 ─┘    │    WM_POWERBROADCAST, WM_QUERYENDSESSION/WM_ENDSESSION        │
                       │              │ 이벤트(즉시 샘플 요청 / 시스템 상태)           │
 GetForegroundWindow   │              ▼                                              │
 GetLastInputInfo ───▶ │  activity/recorder.py  ActivityRecorder (1초 저비용 폴링 보조)│
 OpenInputDesktop      │    ACTIVE / IDLE / LOCKED 구간, 병합, 공백·시계 변경 처리,     │
                       │    10초 배치 플러시 ──▶ activity_span / system_event (SQLite) │
 Chrome/Edge 확장 ──▶  │              ▲                                              │
 (MV3, 활성 탭 도메인) │   browser_state (최신 상태 1행/브라우저) ◀── native host 프로세스│
                       │              │                                              │
                       │  activity/classifier.py → category·confidence·reason·source  │
                       │  activity/auto_sessions.py → auto_session (파생, 재계산 가능) │
                       │  activity/stats.py → 오늘·기간 통계 (구간 클리핑, 중복 없음)   │
                       │  ui/activity_page.py  활동 대시보드 / 트레이 / 온보딩          │
                       │                                                              │
                       │  (기존) SessionService ── 수동 세션 1초 샘플 + 카메라 ──▶ state_sample │
                       └──────────────────────────────────────────────────────────────┘
```

### 시간 회계 원칙 (중복 집계 방지)

- **단일 타임라인**: `activity_span`은 시간상 겹치지 않는다. 한 순간은 `ACTIVE`(앱·도메인), `IDLE`, `LOCKED` 중
  하나이며 절전·FocusLab 미실행·기록 일시정지 시간은 **행이 없다**(사용 시간으로 계산하지 않음).
- 브라우저 활동은 별도 병렬 테이블이 아니라 **브라우저가 맨 앞일 때의 ACTIVE 구간에 붙는 도메인 속성**이다.
  따라서 백그라운드 탭·포커스 잃은 창은 자동으로 제외되고, 앱 합계와 사이트 합계가 모순되지 않는다.
- 자동 세션은 구간의 **그룹**이며 합산 대상이 아니다. 수동 집중 세션과 겹치면 `manual_session_id`로 표시한다.
- 총 PC 사용 = ACTIVE + IDLE (+ LOCKED는 별도 표기), 실제 활성 사용 = ACTIVE.
- 시각은 UTC epoch ms로 저장하고 구간 길이는 **단조 시계**로 늘린다. 벽시계가 단조 시계와 5초 이상 어긋나면
  (시계·시간대 변경) 구간을 끊고 새 시각으로 다시 시작하며 `CLOCK_CHANGED` 이벤트를 남긴다.
- 폴링 간격이 비정상적으로 길면(절전·프로세스 정지) 마지막 관측 시각에서 구간을 닫고 공백을 남긴다.

### 유휴 처리

`GetLastInputInfo` 경과 시간이 임계값(기본 5분, 설정 가능)을 넘으면 **마지막 입력 시각으로 소급**해
ACTIVE 구간을 닫고 IDLE 구간을 시작한다. 입력이 돌아오면 IDLE을 닫고 새 ACTIVE 구간을 연다(복귀 시각 기록).
입력 내용·키·좌표는 읽지 않는다.

## 3. 데이터 모델 (마이그레이션 v2~v5)

권장 이름(`window_activities`, `browser_activities`, `idle_events` …)은 기존 스키마 관례(단수형 테이블,
`feedback` 분리)에 맞춰 다음과 같이 대응한다.

| 권장 | 실제 | 내용 |
| --- | --- | --- |
| `window_activities`, `idle_events` | `activity_span` (`kind` = ACTIVE/IDLE/LOCKED) | 겹치지 않는 시간 구간, `app_id`, `domain`, 분류 결과 |
| `browser_activities` | `activity_span.domain` + `browser_state` | 도메인은 구간 속성, `browser_state`는 확장→본체 최신 상태 |
| `activity_events` | `system_event` | 기록 시작·종료·일시정지, 잠금, 절전, 로그오프, 시계 변경, 복구 |
| (프로그램 식별) | `app` | 소문자 실행 파일 이름(안정 식별자)과 표시 이름 |
| `activity_categories` | 코드 enum `Category` | 10개 고정 카테고리 |
| `classification_rules` | `classification_rule` | 사용자 정정에서 생긴 앱·도메인 규칙 (기본 규칙은 코드) |
| `user_corrections` | `activity_feedback` | 구간별 카테고리 정정 (기존 `feedback`과 같은 구조) |
| `automatic_sessions` | `auto_session` | 자동 감지 세션(파생 데이터, 재계산 가능) |

## 4. 개인정보 기본값

- 저장: 실행 파일 이름(예: `code.exe`), 실행 파일 버전 정보의 제품 설명(예: `Visual Studio Code`), 활성 탭 **hostname**,
  구간 시각, 분류 결과. 저장하지 않음: 창 제목, 실행 파일 전체 경로(사용자 이름 포함 가능), 전체 URL·경로·검색어·페이지 본문,
  키 입력 내용·마우스 좌표, 스크린샷, 카메라 영상.
- 실행 파일 경로는 메모리에서 Steam·Epic 게임 판별 힌트로만 쓰고 버린다.
- PC 기록·브라우저 기록·카메라는 각각 별도 동의. 동의 전·일시정지 중에는 OS를 조회하지 않고 브라우저 상태도 쓰지 않는다.
- 사용자 지정 제외 앱·사이트는 이름 없이 `제외됨`으로만 시간을 남긴다.

## 5. PR 분할

| PR | 브랜치 | 범위 |
| --- | --- | --- |
| PR-A | `feat/activity-collector` | 본 문서, 스키마 v2, Win32 프로브(실행 파일 식별·접근 거부·UWP), `ActivityRecorder`(구간·병합·배치 저장), 포그라운드 이벤트 훅, 앱 연결 |
| PR-B | `feat/idle-system-events` | 유휴 소급 처리, 잠금·절전·로그오프·디스플레이 이벤트, 시계 변경, 비정상 종료 복구, 시작 프로그램, 트레이 상주·일시정지, 최초 실행 동의 |
| PR-C | `feat/browser-tracker` | MV3 확장(Chrome·Edge), Native Messaging host, 등록·해제, 송신자·입력 검증·중복 처리, 도메인 구간 |
| PR-D | `feat/activity-classifier` | 카테고리·규칙 분류, 신뢰도·근거·출처, 사용자 정정 → 규칙 반영, 제외 앱·사이트 |
| PR-E | `feat/auto-sessions` | 자동 세션 감지·저장, 수동 세션·규칙 엔진·카메라 결과와 통합 |
| PR-F | `feat/activity-dashboard` | 오늘 개요·활동 타임라인·통계(일·주·월, 시간대, 전환, 복귀) |
| PR-G | `chore/activity-stability-release` | 보존·내보내기·삭제, 성능 측정, 장시간 실행, 문서·개인정보·CI |

각 PR은 앞 PR 브랜치를 기준(stacked)으로 하며 승인 후 순서대로 머지한다.
