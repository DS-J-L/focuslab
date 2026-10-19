# FocusLab

**Know your workflow, not just your screen time.**

Windows에서 공부·개발 세션의 **작업 패턴을 돌아보기 위한 로컬 우선 오픈소스 앱**을 만듭니다.
사용자가 설정한 목표와 PC 활동, 선택형 웹캠 관찰을 조합하여 작업 관련 활동·잠재적 이탈·자리 비움·판단 불가를 구분하는 것이 목표입니다.

> **현재 상태: 초기 저장소 구조 준비.** 폴더·데이터 계약·상태 안내 CLI·품질 검사 환경만 포함합니다.
> 데스크톱 UI, 실제 센서, SQLite 저장, 타임라인과 리포트는 아직 구현되지 않았습니다. 배포용 설치 파일도 없습니다.

## 어떤 앱을 만드나요?

- **목표와 맥락:** 코딩, 강의, 독서·필기, 사용자 지정 모드와 허용 앱을 고려합니다.
- **설명 가능한 관찰:** 왜 이탈로 추정했는지 보여주고 사용자가 정정할 수 있도록 합니다.
- **불확실성 표현:** 화면 밖을 보거나 카메라를 가렸다는 이유만으로 딴짓을 확정하지 않습니다.
- **로컬 처리:** 계정·클라우드를 강제하지 않고 사용자가 시작한 세션만 관찰합니다.
- **최소 수집:** 원본 영상·음성·스크린샷·키 입력 내용·민감한 창 제목을 저장하지 않는 설계입니다.

FocusLab은 실제 집중력을 직접 측정하거나 ADHD를 진단·치료하는 도구가 아닙니다.
상태와 지표는 관찰 가능한 행동의 추정이며 학습 성과·의학적 판단을 보장하지 않습니다.

## 개발 환경에서 시작하기

대상 환경은 **Windows 11 x64 / Python 3.11 / uv**입니다.
Windows 10 호환성은 별도 검증 대상이며 공식 지원을 약속하지 않습니다.
uv 설치: https://docs.astral.sh/uv/getting-started/installation/

```powershell
git clone https://github.com/DS-J-L/focuslab.git
cd focuslab
uv sync --locked
uv run focuslab
# 또는: uv run python -m focuslab
```

현재 명령은 프로젝트 상태만 출력합니다. 카메라나 PC 활동 수집을 시작하지 않습니다.
PySide6·MediaPipe·OpenCV·Windows API 의존성은 해당 기능 구현 시 호환성 및 라이선스를 확인한 뒤 추가합니다.

```powershell
uv run ruff check .
uv run pytest
uv build
```

GitHub Actions는 Windows runner에서 lint, 테스트, CLI 실행, 패키지 빌드를 확인합니다.
Windows 11 실기기의 카메라·권한·GUI 검증은 별도로 수행해야 합니다.

## 저장소 구조

| 경로 | 역할 |
| --- | --- |
| `src/focuslab/domain/` | 상태·관찰 데이터, 이벤트, 센서/저장/판단 인터페이스 |
| `src/focuslab/camera/` | 카메라, 얼굴 랜드마크, 머리 방향, 보정, 선택형 폰 감지 |
| `src/focuslab/activity/` | Windows 활성 프로그램 및 유휴 상태 |
| `src/focuslab/focus/` | 센서 융합, 모드별 규칙, 지표 |
| `src/focuslab/storage/` | SQLite, 마이그레이션, 저장소 |
| `src/focuslab/services/` | 세션·워커·내보내기 조정 |
| `src/focuslab/ui/` | 메인 창, 세션·리포트·설정 화면, 트레이 |
| `assets/icons/`, `assets/models/` | 출처·라이선스 확인 후 추가할 자산 |
| `tests/unit/`, `tests/integration/`, `tests/e2e/` | 단위·통합·시나리오 검증 |
| `tests/fixtures/` | 합성 관찰 데이터 중심의 테스트 자료 |
| `.github/` | Windows CI, 이슈·PR 템플릿 |

빈 구현 모듈에는 담당 역할과 예정 PR을 명시했습니다. 실제 기능을 제공하는 것처럼 보이는 가짜 구현은 없습니다.

## 관찰 상태

| 상태 | 의미 |
| --- | --- |
| `ON_TASK` | 목표 관련 활동으로 추정 |
| `POSSIBLY_OFF_TASK` | 작업 이탈 가능성 |
| `AWAY` | 자리 비움으로 추정 |
| `BREAK` | 사용자가 지정한 휴식 |
| `UNKNOWN` | 관찰 부족·센서 오류 등으로 판단 불가 |

카메라 미사용을 낮은 점수로 처리하지 않으며 `UNKNOWN`, 휴식, 자리 비움은 별도로 보여줄 계획입니다.
기본 앱만으로 브라우저의 사이트 관련성을 알 수는 없습니다. hostname을 사용하는 선택형 Chrome 확장은 PR-09 범위입니다.

## 개발 로드맵

| 단계 | 범위 | 상태 |
| --- | --- | --- |
| PR-00 | 오픈소스 문서·구조·개발 환경, 모의 센서·기본 PySide6 창 | 구조·문서·CLI 준비; UI·모의 센서·Windows 11 실기기 검증 남음 |
| PR-01–02 | 세션 수명주기·SQLite·카메라 | 예정 |
| PR-03–06 | 얼굴 관찰·보정·Windows 활동·판단 엔진 | 예정 |
| PR-07–08 | 대시보드·내보내기·삭제, v0.1 MVP | 예정 |
| PR-09 | 선택형 Chrome 확장 | 예정 |
| PR-10–11 | 선택형 폰 감지·개인화·알림, v0.2 | 예정 |
| PR-12–13 | 실사용 검증·성능·라이선스·Windows 설치 배포 | 예정 |

완료 조건과 설계의 기준 문서는 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)입니다.
각 기능은 브랜치 → PR → 검사·Windows 확인 → 리뷰 → 머지 순서로 진행합니다.
FocusLab은 작업명이며 공개 제품 배포 전에 동명 서비스·상표 사용 가능성을 검토합니다.

## 기여와 정책

- [기여 안내](CONTRIBUTING.md) · [행동 강령](CODE_OF_CONDUCT.md)
- [개인정보 원칙](PRIVACY.md) · [보안 제보](SECURITY.md)
- [개발 계획](DEVELOPMENT_PLAN.md) · [제3자 고지](THIRD_PARTY_NOTICES.md)

프로젝트 자체 코드는 [Apache License 2.0](LICENSE)으로 공개합니다.
외부 패키지·Qt·ML 모델은 각각의 라이선스를 따릅니다. 현재 모델과 외부 런타임은 포함하지 않습니다.
