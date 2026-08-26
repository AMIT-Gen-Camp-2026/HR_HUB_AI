"""
app/asgi.py

نقطة الدخول الرئيسية للتطبيق الجديد (FastAPI). بيجمع كل الـ routers،
يفعّل الـ exception handler الموحد من app/errors.py، ويربط الإعدادات
(Settings/Features) بحياة التطبيق (lifespan) عشان تبقى متاحة لكل
الـ requests من غير ما كل route يعمل get_settings() لوحده.

مهم: كل الـ routers متسجلين دايمًا هنا - الـ feature flags (cv_parsing,
ranking, assistant) بيتم التحقق منها *جوه* كل route handler، مش هنا.
لو feature مقفولة، الـ route نفسه هو اللي يرمي app.errors.FeatureDisabled
(status=200 - "documented state, not an error" زي ما موضح في errors.py)
بدل ما الـ endpoint يختفي تمامًا برجوع 404.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import get_features, get_settings
from app.errors import register_exception_handlers
from app.prompts.registry import PromptRegistry

from app.api import routes_health
from app.api import routes_cv
from app.api import routes_ranking
from app.api import routes_assistant


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    بتتشغل مرة واحدة وقت الـ startup: بتحمّل الإعدادات والـ prompts
    وتحطهم في app.state عشان أي route يقدر يوصلهم من غير استيراد
    مباشر لـ get_settings()/get_features() جوه كل دالة.
    """
    settings = get_settings()
    features = get_features()

    app.state.settings = settings
    app.state.features = features
    app.state.prompts = PromptRegistry(prompts_dir=settings.prompts_dir)

    yield

    # مفيش حاجة محتاجة cleanup دلوقتي (مفيش connections مفتوحة بشكل دائم)


def create_app() -> FastAPI:
    """Application factory - بيسهّل استخدام نفس الإعداد في التستات (tests/conftest.py)."""
    app = FastAPI(
        title="AMIT Instructor Hub — AI Service",
        lifespan=lifespan,
    )

    # كل الـ routers متسجلين دايمًا - مفيش أي feature gating هنا.
    # راجع الـ docstring فوق: الـ gating بيحصل جوه كل route handler.
    app.include_router(routes_health.router)
    app.include_router(routes_cv.router)
    app.include_router(routes_ranking.router)
    app.include_router(routes_assistant.router)

    register_exception_handlers(app)

    return app


app = create_app()