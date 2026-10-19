# 기여 안내

먼저 [개발 계획](DEVELOPMENT_PLAN.md)과 [개인정보 원칙](PRIVACY.md)을 읽어 주세요.
현재 범위는 초기 저장소 구조입니다. PR-00의 UI·모의 센서·Windows 검증은 후속 작업으로 남아 있습니다.

## Windows PowerShell 개발 환경

Python 3.11과 uv가 필요합니다. uv 설치는 https://docs.astral.sh/uv/getting-started/installation/ 을 참고하세요.

```powershell
git clone https://github.com/DS-J-L/focuslab.git
cd focuslab
uv sync --locked
uv run focuslab
uv run ruff check .
uv run pytest
uv build
```

## 작업 흐름

1. 이슈에서 범위와 개인정보 영향을 정리합니다.
2. `feat/<scope>` 또는 `fix/<scope>` 브랜치에서 한 가지 목적만 구현합니다.
3. 센서는 관찰값만 발행하고 판단 로직·UI·저장소와 분리합니다.
4. lint·테스트·필요한 Windows 실제 검증 결과를 PR에 남깁니다.
5. 검증 및 리뷰 후 squash merge합니다. PR-00 완료 전 PR-01에 착수하지 않습니다.

합성 이벤트를 기본 테스트 데이터로 사용하고 원본 카메라 영상·사용자 기록·비밀키를 커밋하지 마세요.
의존성 추가 시 Windows Python 3.11에서 호환성을 확인하고 uv.lock 및 제3자 고지를 갱신하세요.
README는 한국어를 기준으로 관리하며 영어 번역 PR을 환영합니다. 기능 완료 여부와 설명은 번역 간 일치해야 합니다.
