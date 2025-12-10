# core/api_keys.py
import os
import json
from typing import Tuple

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS_DIR = os.path.join(BASE_DIR, "data", "secrets")
KEYS_FILE = os.path.join(SECRETS_DIR, "binance_api_keys.json")


def load_api_keys() -> Tuple[str, str]:
    """تحميل API Key و Secret من ملف JSON (لو موجود)."""
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("api_key", "")), str(data.get("api_secret", ""))
    except Exception:
        return "", ""


def save_api_keys(api_key: str, api_secret: str) -> None:
    """حفظ المفاتيح في ملف، وإنشاء المجلد لو ما كان موجود."""
    os.makedirs(SECRETS_DIR, exist_ok=True)
    data = {
        "api_key": api_key.strip(),
        "api_secret": api_secret.strip(),
    }
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
