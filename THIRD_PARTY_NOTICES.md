# Third-party dependencies and assets

Current application runtime dependencies: none. No Qt, OpenCV, MediaPipe runtime or ML model is bundled in this scaffold. Development/build dependencies are recorded in pyproject.toml and uv.lock and retain their respective licenses.

## Required review before adding dependencies or shipping binaries

| Planned component | Required review |
| --- | --- |
| PySide6 / Qt | Verify the exact packages, LGPLv3/GPLv3/commercial terms, distribution and relinking obligations. |
| OpenCV | Verify the chosen package version and bundled third-party notices. |
| MediaPipe | Check source/package licensing separately from every model asset. |
| .task / .tflite model files | Record original source, exact version, license, redistribution permission and SHA256. |
| pywin32 / psutil / NumPy | Record exact package licenses and applicable notices. |

Apache-2.0 applies to original FocusLab code; it does not relicense dependencies, models or trademarks. Do not commit or distribute a model until its review is recorded here.
