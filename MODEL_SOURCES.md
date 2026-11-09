# 模型来源

模型不会提交到 Git；`scripts/download_models.py` 下载以下 MediaPipe 模型，并在使用前校验 SHA-256。

| 文件 | 来源 | SHA-256 |
| --- | --- | --- |
| `gesture_recognizer.task` | [MediaPipe Gesture Recognizer](https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task) | `97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482` |
| `pose_landmarker_lite.task` | [MediaPipe Pose Landmarker Lite](https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task) | `59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a` |

OK 锁定手势基于 MediaPipe 输出的 21 个手部关键点进行几何判定，不需要单独的训练模型。
模型许可和使用条件以 MediaPipe 模型发布条款为准。重新分发模型文件前请检查对应许可。
