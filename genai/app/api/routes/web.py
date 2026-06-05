from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response


router = APIRouter(tags=["web"])

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@router.get("/", include_in_schema=False)
async def web_app() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@router.head("/", include_in_schema=False)
async def web_app_head() -> Response:
    return Response(status_code=200)


@router.get("/quiz.html", include_in_schema=False)
async def quiz_page() -> FileResponse:
    return FileResponse(WEB_DIR / "quiz.html")