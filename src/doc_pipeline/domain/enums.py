from enum import StrEnum


class DocumentStatus(StrEnum):
    DRAFT = "DRAFT"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    SCANNING = "SCANNING"
    EXTRACTING = "EXTRACTING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DocumentType(StrEnum):
    INVOICE = "INVOICE"
    KYC = "KYC"
    CONTRACT = "CONTRACT"


class JobType(StrEnum):
    INGESTION = "INGESTION"
    PROCESSING = "PROCESSING"


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    STUCK = "STUCK"
    CANCELLED = "CANCELLED"


class UploadStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    ABORTED = "ABORTED"


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    OPERATOR = "OPERATOR"
