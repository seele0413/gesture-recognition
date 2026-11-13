from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT_DIR / "web"
MODEL_DIR = ROOT_DIR / "models"
DATA_DIR = ROOT_DIR / "data"
MEDIA_DIR = ROOT_DIR / "media"
MAX_INFERENCE_WIDTH = 960
PROMO_VIDEO_PATH = MEDIA_DIR / "company-promo.mp4"
DATABASE_PATH = DATA_DIR / "identities.sqlite3"

# Add approved media and deck IDs here. Client requests never provide filesystem paths.
MEDIA_ASSETS: dict[str, dict[str, str]] = {
    "company-promo": {"title": "企业宣传片", "filename": "company-promo.mp4"},
}
PRESENTATION_DECKS: dict[str, dict[str, str]] = {}

MODEL_FILES = {
    "gesture": "gesture_recognizer.task",
    "pose": "pose_landmarker_lite.task",
}
