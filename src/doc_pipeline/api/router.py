from fastapi import APIRouter

from doc_pipeline.api.v1.admin import router as admin_router
from doc_pipeline.api.v1.audit import router as audit_router
from doc_pipeline.api.v1.documents import router as documents_router
from doc_pipeline.api.v1.health import router as health_router
from doc_pipeline.api.v1.jobs import router as jobs_router
from doc_pipeline.api.v1.uploads import router as uploads_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(documents_router)
api_router.include_router(uploads_router)
api_router.include_router(jobs_router)
api_router.include_router(audit_router)
api_router.include_router(admin_router)
