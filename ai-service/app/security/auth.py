"""
app/security/auth.py

حماية بسيطة بـ API key ثابت بين الـ ai-service وأي حد بيناديه (غالبًا الـ
full-stack backend). دي خطوة أولى سريعة قبل الـ integration - مش بديل عن
auth layer حقيقي (JWT/OAuth) لو المشروع كبر واحتاج مستخدمين متعددين
بصلاحيات مختلفة. انظر docs/DECISIONS.md لتفاصيل القرار ده.
"""
from __future__ import annotations

import hmac
import logging
from functools import wraps

from flask import jsonify, request

from config.settings import config

logger = logging.getLogger(__name__)

_warned_once = False


def require_api_key(view_func):
    """
    بتتحقق من header اسمه X-API-Key ومطابق لـ config.AI_SERVICE_API_KEY.

    لو AI_SERVICE_API_KEY فاضي (مش متظبط في .env)، الـ endpoint بيفضل شغال
    من غير حماية - fail-open مقصود عشان التطوير المحلي والـ tests الحالية
    تفضل شغالة من غير تعديل، لكن بيطبع warning واحد بس في اللوج (مش في كل
    request) عشان ميتنساش قبل أي deployment حقيقي.
    """

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        global _warned_once
        if not config.AI_SERVICE_API_KEY:
            if not _warned_once:
                logger.warning(
                    "AI_SERVICE_API_KEY مش متظبط - الـ endpoints شغالة من غير أي "
                    "حماية. مقبول للتطوير المحلي بس - لازم يتظبط قبل أي deployment "
                    "متاح لغير جهازك."
                )
                _warned_once = True
            return view_func(*args, **kwargs)

        provided = request.headers.get("X-API-Key", "")
        # hmac.compare_digest بدل == عشان نتجنب timing attack بسيط على طول المفتاح.
        if not hmac.compare_digest(provided, config.AI_SERVICE_API_KEY):
            return jsonify({"success": False, "error": "Missing or invalid API key."}), 401

        return view_func(*args, **kwargs)

    return wrapped