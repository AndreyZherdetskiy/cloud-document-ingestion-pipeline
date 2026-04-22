"""OpenTelemetry SDK bootstrap — OTLP to Collector (gRPC on :4317)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

if TYPE_CHECKING:
    from doc_pipeline.config.settings import Settings

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None

FORBIDDEN_METRIC_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"document_id", "correlation_id"},
)


def assert_low_cardinality_attrs(attributes: Mapping[str, str]) -> dict[str, str]:
    for key in attributes:
        if key in FORBIDDEN_METRIC_ATTRIBUTES:
            msg = f"high-cardinality metric attribute forbidden: {key}"
            raise ValueError(msg)
    return dict(attributes)


def build_resource(service_name: str) -> Resource:
    return Resource.create({"service.name": service_name})


def _grpc_endpoint(endpoint: str) -> str:
    cleaned = endpoint.removeprefix("http://").removeprefix("https://")
    return cleaned.rstrip("/")


def configure_otel(service_name: str, settings: Settings) -> None:
    global _tracer_provider, _meter_provider

    if settings.otel_sdk_disabled:
        return

    resource = build_resource(service_name)
    grpc_target = _grpc_endpoint(settings.otel_exporter_otlp_endpoint)

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=grpc_target, insecure=True),
        ),
    )
    trace.set_tracer_provider(tracer_provider)
    _tracer_provider = tracer_provider

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=grpc_target, insecure=True),
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter_provider = meter_provider


def shutdown_otel() -> None:
    global _tracer_provider, _meter_provider

    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None

    if _meter_provider is not None:
        _meter_provider.shutdown()
        _meter_provider = None


def instrument_fastapi(app: FastAPI, settings: Settings) -> None:
    if settings.otel_sdk_disabled:
        return
    FastAPIInstrumentor.instrument_app(app)


def get_tracer_provider() -> TracerProvider | None:
    return _tracer_provider


def get_meter_provider() -> MeterProvider | None:
    return _meter_provider
