"""FinSwipe GenAI Server — FastAPI 엔트리포인트"""
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_pool, close_pool
from app.routers import health, news, quiz, legacy

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 DB 풀 초기화/해제"""
    settings = get_settings()
    logger.info("GenAI 서버 시작 (포트 %d)", settings.port)
    await create_pool()
    logger.info("DB 풀 초기화 완료")
    yield
    await close_pool()
    logger.info("DB 풀 해제 완료")


app = FastAPI(
    title="FinSwipe GenAI API",
    description="금융 뉴스 분석 및 사용자 레벨 테스트 서버",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정
settings = get_settings()
origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(health.router)
app.include_router(news.router)
app.include_router(quiz.router)
app.include_router(legacy.router)  # /api/v1/articles/enrich-text (Spring Boot 호환)


@app.get("/")
async def root():
    return {
        "service": "FinSwipe GenAI",
        "version": "1.0.0",
        "endpoints": [
            "GET  /health",
            "POST /news/analyze",
            "GET  /news/summary/{ticker}",
            "POST /quiz/start",
            "GET  /quiz/question/{session_id}",
            "POST /quiz/answer",
            "GET  /quiz/result/{session_id}",
            "POST /api/v1/articles/enrich-text  (Spring Boot 호환)",
        ],
    }
