"""Compose stack contract tests (ports, workers, observability wiring)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

COMPOSE_PATH = Path("docker-compose.yml")
PERF_COMPOSE_PATH = Path("docker-compose.perf.yml")
MAKEFILE_PATH = Path("Makefile")
COLLECTOR_PATH = Path("infra/otel/collector.yaml")
PROMETHEUS_PATH = Path("infra/prometheus/prometheus.yml")
GRAFANA_DOCKERFILE = Path("infra/grafana/Dockerfile")
GRAFANA_DASHBOARDS_YML = Path("infra/grafana/provisioning/dashboards/dashboards.yml")

GRAFANA_DASHBOARDS_PATH = "/etc/grafana/dashboards"
FORBIDDEN_GRAFANA_DASHBOARDS_PATH = "/var/lib/grafana/dashboards"

BAKED_CONFIG_SERVICES = (
    "localstack",
    "otel-collector",
    "prometheus",
    "grafana",
)

NO_ENV_FILE_SERVICES = (
    "postgres",
    "localstack",
    "api",
    "ingestion-worker",
    "processing-worker",
    "stuck-scanner",
)


def _bind_mount_sources(service: dict[str, Any]) -> list[str]:
    sources: list[str] = []
    for volume in service.get("volumes") or []:
        if isinstance(volume, str):
            source = volume.split(":", 1)[0]
            sources.append(source)
        elif isinstance(volume, dict) and volume.get("type") == "bind":
            sources.append(str(volume.get("source") or ""))
    return sources


@pytest.fixture(scope="module")
def compose_data() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compose_services(compose_data: dict) -> dict:
    return compose_data["services"]


@pytest.fixture(scope="module")
def perf_compose_data() -> dict:
    return yaml.safe_load(PERF_COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_project_name(compose_data: dict) -> None:
    assert compose_data.get("name") == "doc-pipeline"
    network = (compose_data.get("networks") or {}).get("default") or {}
    assert network.get("name") == "doc-pipeline"


@pytest.mark.parametrize(
    ("service", "host_port"),
    [
        pytest.param("postgres", "5432", id="postgres:5432"),
        pytest.param("redis", "6379", id="redis:6379"),
        pytest.param("localstack", "4566", id="localstack:4566"),
        pytest.param("api", "8000", id="api:8000"),
        pytest.param("otel-collector", "4317", id="otel-collector:4317"),
        pytest.param("otel-collector", "4318", id="otel-collector:4318"),
        pytest.param("prometheus", "9090", id="prometheus:9090"),
        pytest.param("grafana", "3000", id="grafana:3000"),
        pytest.param("jaeger", "16686", id="jaeger:16686"),
    ],
)
def test_compose_service_host_port(
    compose_services: dict,
    service: str,
    host_port: str,
) -> None:
    assert service in compose_services
    ports = compose_services[service].get("ports") or []
    flat = " ".join(str(port) for port in ports)
    assert host_port in flat, f"{service} missing host port {host_port}"


def test_split_workers_no_generic_worker(compose_services: dict) -> None:
    assert "ingestion-worker" in compose_services
    assert "processing-worker" in compose_services
    assert "worker" not in compose_services


@pytest.mark.parametrize("svc", ["ingestion-worker", "processing-worker"])
def test_workers_do_not_publish_host_ports(compose_services: dict, svc: str) -> None:
    assert not compose_services[svc].get("ports"), f"{svc} must not publish host ports"


def test_worker_commands(compose_services: dict) -> None:
    ingestion = compose_services["ingestion-worker"]
    processing = compose_services["processing-worker"]
    assert "ingestion_main" in " ".join(str(part) for part in (ingestion.get("command") or []))
    assert "processing_main" in " ".join(str(part) for part in (processing.get("command") or []))


@pytest.mark.parametrize("svc", ["ingestion-worker", "processing-worker"])
def test_workers_sqs_processing_queue_url(compose_services: dict, svc: str) -> None:
    env = compose_services[svc].get("environment") or {}
    assert "SQS_PROCESSING_QUEUE_URL" in env


def test_workers_otel_service_names(compose_services: dict) -> None:
    ingestion_env = compose_services["ingestion-worker"].get("environment", {})
    processing_env = compose_services["processing-worker"].get("environment", {})
    assert ingestion_env.get("OTEL_SERVICE_NAME") == "doc-pipeline-ingestion-worker"
    assert processing_env.get("OTEL_SERVICE_NAME") == "doc-pipeline-processing-worker"


def test_collector_otlp_metrics_prometheus_traces_jaeger_no_tempo() -> None:
    collector_text = COLLECTOR_PATH.read_text(encoding="utf-8")
    assert "tempo" not in collector_text.lower()
    assert "otlp" in collector_text.lower()

    collector = yaml.safe_load(collector_text)
    exporters = collector.get("exporters", {})
    assert "prometheus" in exporters
    assert any("jaeger" in name.lower() for name in exporters)

    pipelines = collector.get("service", {}).get("pipelines", {})
    assert "prometheus" in pipelines.get("metrics", {}).get("exporters", [])
    trace_exporters = pipelines.get("traces", {}).get("exporters", [])
    assert any("jaeger" in name.lower() for name in trace_exporters)


def test_prometheus_scrapes_otel_collector() -> None:
    prom = yaml.safe_load(PROMETHEUS_PATH.read_text(encoding="utf-8"))
    jobs = {job["job_name"]: job for job in prom.get("scrape_configs", [])}
    assert "otel-collector" in jobs
    targets = jobs["otel-collector"]["static_configs"][0]["targets"]
    assert "otel-collector:8889" in targets


def test_grafana_admin_from_env_not_literal(compose_services: dict) -> None:
    compose_text = COMPOSE_PATH.read_text(encoding="utf-8")
    grafana = compose_services["grafana"]
    env = grafana.get("environment", {})
    assert env.get("GF_SECURITY_ADMIN_USER") == "${GF_SECURITY_ADMIN_USER}"
    assert env.get("GF_SECURITY_ADMIN_PASSWORD") == "${GF_SECURITY_ADMIN_PASSWORD}"
    assert "GF_SECURITY_ADMIN_PASSWORD: admin" not in compose_text
    assert "GF_SECURITY_ADMIN_USER: admin" not in compose_text


@pytest.mark.parametrize("name", BAKED_CONFIG_SERVICES)
def test_baked_config_services_have_no_host_bind_mounts(
    compose_services: dict,
    name: str,
) -> None:
    for source in _bind_mount_sources(compose_services[name]):
        assert not source.startswith("./infra")
        assert not source.startswith("./docs/grafana")


@pytest.mark.parametrize(
    ("name", "context", "dockerfile"),
    (
        ("localstack", "./infra/localstack", "Dockerfile"),
        ("otel-collector", "./infra/otel", "Dockerfile"),
        ("prometheus", "./infra/prometheus", "Dockerfile"),
        ("grafana", ".", "infra/grafana/Dockerfile"),
    ),
)
def test_observability_services_bake_configs_in_images(
    compose_services: dict,
    name: str,
    context: str,
    dockerfile: str,
) -> None:
    build = compose_services[name].get("build") or {}
    assert build.get("context") == context
    assert build.get("dockerfile") == dockerfile


@pytest.mark.parametrize("name", NO_ENV_FILE_SERVICES)
def test_no_env_file_on_app_and_data_plane_services(
    compose_services: dict,
    name: str,
) -> None:
    """Host .env has localhost DSNs — must not dump into containers (C3)."""
    assert "env_file" not in compose_services[name]


def test_grafana_dashboards_provisioned_outside_data_volume() -> None:
    """Dashboards must live under /etc/grafana so grafana_data cannot shadow them (C2)."""
    dockerfile = GRAFANA_DOCKERFILE.read_text(encoding="utf-8")
    assert GRAFANA_DASHBOARDS_PATH in dockerfile
    assert FORBIDDEN_GRAFANA_DASHBOARDS_PATH not in dockerfile

    doc = yaml.safe_load(GRAFANA_DASHBOARDS_YML.read_text(encoding="utf-8"))
    providers = doc.get("providers") or []
    assert providers, "dashboards.yml: expected providers"
    path = providers[0].get("options", {}).get("path")
    assert path == GRAFANA_DASHBOARDS_PATH


def test_grafana_data_volume_mounts_var_lib_only(
    compose_services: dict,
    compose_data: dict,
) -> None:
    volumes = compose_services["grafana"].get("volumes") or []
    assert "grafana-data:/var/lib/grafana" in volumes
    grafana_vol = (compose_data.get("volumes") or {}).get("grafana-data") or {}
    assert grafana_vol.get("name") == "doc-pipeline-grafana-data"


def test_api_compose_healthcheck_hits_ready(compose_services: dict) -> None:
    healthcheck = compose_services["api"].get("healthcheck") or {}
    test = healthcheck.get("test") or []
    flat = " ".join(str(part) for part in test)
    assert "/v1/ready" in flat
    assert "urllib" in flat or "urllib.request" in flat


def test_otel_collector_healthcheck_disabled(compose_services: dict) -> None:
    healthcheck = compose_services["otel-collector"].get("healthcheck") or {}
    assert healthcheck.get("disable") is True


def test_jwt_public_key_has_no_host_bind(compose_services: dict) -> None:
    """API must use JWT_PUBLIC_KEY_PEM via env — no public.pem / JWT_PUBLIC_KEY_FILE bind."""
    api = compose_services["api"]
    volumes = api.get("volumes") or []
    flat = " ".join(str(volume) for volume in volumes)
    assert "public.pem" not in flat
    assert "JWT_PUBLIC_KEY_FILE" not in flat
    env = api.get("environment") or {}
    assert env.get("JWT_PUBLIC_KEY_PEM") == "${JWT_PUBLIC_KEY_PEM}"
    path = env.get("JWT_PUBLIC_KEY_PATH", "")
    assert path in ("", '""') or path is None


def test_compose_up_uses_wait() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "compose-up:" in text
    after = text.split("compose-up:", 1)[1]
    target_body = after.split("\n\n", 1)[0]
    assert "--wait" in target_body


def test_no_tempo_or_kafka_services(compose_services: dict) -> None:
    for name in compose_services:
        assert "tempo" not in name.lower()
        assert "kafka" not in name.lower()


def test_perf_compose_file_exists() -> None:
    assert PERF_COMPOSE_PATH.is_file()


def test_perf_overlay_api_uvicorn_workers(perf_compose_data: dict) -> None:
    cmd = perf_compose_data["services"]["api"]["command"]
    flat = " ".join(str(part) for part in cmd)
    assert "--workers" in flat
    assert "4" in flat
    assert "doc_pipeline.main:create_app" in flat
    assert "--factory" in flat


def test_perf_overlay_api_rate_limit_unlimited(perf_compose_data: dict) -> None:
    env = perf_compose_data["services"]["api"]["environment"]
    assert env.get("RATE_LIMIT_PER_MINUTE") == "0"


def test_makefile_perf_up_scales_consumers_only() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    assert "perf-up:" in text
    block = text.split("perf-up:")[1].split("\n\n")[0]
    assert "docker-compose.perf.yml" in block
    assert "--scale ingestion-worker=2" in block
    assert "--scale processing-worker=2" in block
    assert "--scale api" not in block


def test_compose_up_has_no_scale() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    after = text.split("compose-up:", 1)[1]
    target_body = after.split("\n\n", 1)[0]
    assert "--scale" not in target_body


def test_stack_down_includes_perf_overlay_and_remove_orphans() -> None:
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    down = text.split("stack-down:")[1].split("\n\n")[0]
    assert "docker-compose.perf.yml" in down
    assert "--remove-orphans" in down
