from fastapi import APIRouter
from app.database import get_pool

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """서버 및 DB 상태 확인 — Spring Boot AnalyzerService.checkHealth() 호출 대상"""
    # DB 연결 확인
    try:
        pool = get_pool()
        await pool.fetchval("SELECT 1")
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"

    return {
        "status": "ok",
        "db": db_status,
        "service": "finswipe-genai",
    }
