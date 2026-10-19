# Models

모델 파일은 저장소에 커밋하지 않습니다. 아래 명령이 공식 MediaPipe 저장소에서 받아 SHA256을 확인한 뒤 이 폴더에 저장합니다.

```powershell
uv run focuslab --fetch-models
```

| 파일 | 용도 | 출처·체크섬 |
| --- | --- | --- |
| `face_landmarker.task` | 얼굴 존재·머리 방향 (MediaPipe FaceLandmarker) | [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md) |

새 모델은 라이선스·재배포 권한을 확인하고 출처, 버전, SHA256을 THIRD_PARTY_NOTICES.md에 기록한 뒤에만 추가하세요.
