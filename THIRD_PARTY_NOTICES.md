# 第三方组件与素材说明

本交付保留项目完整 Python、HTML、CSS、JavaScript 源码。项目已有的品牌和宣传片素材随本次交付保留，不为这些素材额外授予使用权。

## 运行环境

- Python 3.12.14 x64，构建号 20260814，来自本机已验证的 Astral python-build-standalone 发行环境。Python 许可原文位于 `runtime/LICENSE.txt` 与 `licenses/Python-LICENSE.txt`。
- 独立发行环境说明：https://docs.astral.sh/python-build-standalone/ 。运行环境作为应用的私有目录交付，不依赖原开发机的虚拟环境路径。
- Python-build-standalone 项目许可与依赖说明：https://github.com/astral-sh/python-build-standalone/blob/main/LICENSE 、https://github.com/astral-sh/python-build-standalone/blob/main/python-licenses.rst 。

## Python 依赖

准确版本见 `requirements-lock.txt` 与 `RELEASE.json`，保留各依赖的 `.dist-info` 元数据与随包许可，并另汇总到 `licenses/`。主要组件为 FastAPI、Starlette、Uvicorn、MediaPipe、PyAV、OpenCV、NumPy、Pydantic、pypdf；Windows 运行包额外包含 pywin32 311，用于可选的 PowerPoint COM 控制。

PyAV / FFmpeg、OpenCV 及 MediaPipe 包内包含其各自原生依赖；许可文本以随包保留的原文为准。PowerPoint 软件、第三方网站和 AI 模型服务不在运行包中提供。

## 模型与素材

- MediaPipe Gesture Recognizer 与 Pose Landmarker Lite 的原始下载地址和 SHA-256 见 `MODEL_SOURCES.md`。
- 官方模型说明：https://developers.google.com/edge/mediapipe/solutions/vision/gesture_recognizer 、https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker 。
- COMKING 标识沿用现有项目素材，保存为 `web/assets/comking-logo.jpg`，避免管理页面离线加载失败。原素材地址：https://img.kompass.com/sys-master-images/h29/h63/9109303525406/comking%E6%96%B0logo-jpg 。
- 企业宣传片沿用现有项目的 `media/company-promo.mp4`。

本说明用于记录交付组成与来源，具体许可文本保留在对应组件目录中。
