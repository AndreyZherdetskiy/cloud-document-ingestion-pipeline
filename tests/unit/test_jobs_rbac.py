"""Jobs API RBAC and transition rules."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import TENANT_A
from tests.fixtures.jwt_keys import mint_token

from doc_pipeline.domain.enums import JobStatus, JobType
from doc_pipeline.domain.ids import generate_uuidv7
from doc_pipeline.domain.services.job_service import InMemoryJobService, JobRecord


@pytest.fixture
async def operator_client(app) -> AsyncIterator[AsyncClient]:
    token = mint_token(tenant_id=str(TENANT_A), roles=["ROLE_OPERATOR"])
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


@pytest.fixture
def succeeded_job_id(job_service: InMemoryJobService) -> UUID:
    job_id = generate_uuidv7()
    doc_id = generate_uuidv7()
    job_service.seed(
        JobRecord(
            id=job_id,
            document_id=doc_id,
            tenant_id=TENANT_A,
            job_type=JobType.INGESTION,
            status=JobStatus.SUCCEEDED,
            attempt=1,
        )
    )
    return job_id


@pytest.mark.asyncio
async def test_retry_invalid_status_409(
    operator_client: AsyncClient,
    succeeded_job_id: UUID,
) -> None:
    r = await operator_client.post(f"/v1/jobs/{succeeded_job_id}/retry")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_retry_forbidden_for_api_client(
    api_client_tenant_a: AsyncClient,
    succeeded_job_id: UUID,
) -> None:
    r = await api_client_tenant_a.post(f"/v1/jobs/{succeeded_job_id}/retry")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_retry_failed_job_ok(
    operator_client: AsyncClient,
    job_service: InMemoryJobService,
) -> None:
    job_id = generate_uuidv7()
    job_service.seed(
        JobRecord(
            id=job_id,
            document_id=generate_uuidv7(),
            tenant_id=TENANT_A,
            job_type=JobType.INGESTION,
            status=JobStatus.FAILED,
            attempt=2,
        )
    )
    r = await operator_client.post(f"/v1/jobs/{job_id}/retry")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PENDING"
    assert body["attempt"] == 3
