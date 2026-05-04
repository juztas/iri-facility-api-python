#!/usr/bin/env python3
"""Main API application"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased, ParentBased
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from . import config
from .apilogger import configure_logging

from app.routers.error_handlers import install_error_handlers
from app.routers.facility import facility
from app.routers.status import status
from app.routers.account import account
from app.routers.compute import compute
from app.routers.filesystem import filesystem
from app.routers.task import task

configure_logging(config.LOG_LEVEL)

# ------------------------------------------------------------------
# OpenTelemetry Configuration
# ------------------------------------------------------------------
meter_provider = None
if config.OPENTELEMETRY_ENABLED:
    resource = Resource.create({"service.name": "iri-facility-api", "service.version": config.API_VERSION, "service.endpoint": config.API_URL_ROOT})

    if config.OTEL_TRACES_ENABLED:
        samplerate = "1.0" if config.OPENTELEMETRY_DEBUG else config.OTEL_SAMPLE_RATE
        tracer_provider = TracerProvider(resource=resource, sampler=ParentBased(TraceIdRatioBased(samplerate)))
        if config.OTLP_ENDPOINT:
            span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=config.OTLP_ENDPOINT, insecure=True))
        else:
            span_processor = SimpleSpanProcessor(ConsoleSpanExporter())
        tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(tracer_provider)

    if config.OTEL_METRICS_ENABLED:
        if config.OTLP_ENDPOINT:
            metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=config.OTLP_ENDPOINT, insecure=True), export_interval_millis=config.OTEL_METRIC_EXPORT_INTERVAL)
        else:
            metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=config.OTEL_METRIC_EXPORT_INTERVAL)
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
# ------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    logger = logging.getLogger(__name__)
    for r in [task.router, filesystem.router]:
        for attr in ("adapter", "task_adapter"):
            adapter = getattr(r, attr, None)
            ctrl = getattr(adapter, "task_controller", None)
            if ctrl and hasattr(ctrl, "close"):
                logger.info("Calling close for %s.%s", r.prefix, attr)
                await ctrl.close()
    if meter_provider:
        meter_provider.shutdown()

APP = FastAPI(servers=[{"url": config.API_URL_ROOT}], lifespan=lifespan, **config.API_CONFIG)

if config.OPENTELEMETRY_ENABLED:
    FastAPIInstrumentor.instrument_app(APP)

install_error_handlers(APP)

api_prefix = f"{config.API_PREFIX}{config.API_URL}"

# Attach routers under the prefix
APP.include_router(facility.router, prefix=api_prefix)
APP.include_router(status.router, prefix=api_prefix)
APP.include_router(account.router, prefix=api_prefix)
APP.include_router(compute.router, prefix=api_prefix)
APP.include_router(filesystem.router, prefix=api_prefix)
APP.include_router(task.router, prefix=api_prefix)

logging.getLogger().info(f"API path: {api_prefix}")
