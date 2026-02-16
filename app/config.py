import os
import logging
import json

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)

API_VERSION = "1.0.0"

# lines in the description can't have indentation (markup format)
description = """
A simple implementation of the IRI facility API using Python and the FastAPI library.

For more information, see: [https://iri.science/](https://iri.science/)

<img src="https://iri.science/images/doe-icon-old.png" height=50 />
"""

# version is the openapi.json spec version
# /api/v1 mount point means it's the latest backward-compatible url
API_CONFIG = {
    "title": "IRI Facility API reference implementation",
    "description": description,
    "version": API_VERSION,
    "docs_url": "/",
    "contact": {"name": "The IRI Interfaces Subcommittee", "url": "https://iri.science/ts/interfaces/"},
    "terms_of_service": """IRI Facility API Copyright (c) 2025. The Regents of the University
    of California, through Lawrence Berkeley National Laboratory (subject to receipt
    of any required approvals from the U.S. Dept. of Energy).  All rights reserved.""",
    "license": {"name": "BSD-3-Clause", "url": "https://opensource.org/license/bsd-3-clause/"}
}
try:
    # optionally overload the init params
    d2 = json.loads(os.environ.get("IRI_API_PARAMS", "{}"))
    API_CONFIG.update(d2)
except Exception as exc:
    logging.getLogger().error(f"Error parsing IRI_API_PARAMS: {exc}")


API_URL_ROOT = os.environ.get("API_URL_ROOT", "https://api.iri.nersc.gov")
API_PREFIX = os.environ.get("API_PREFIX", "/")
API_URL = os.environ.get("API_URL", "api/v1")

OPENTELEMETRY_ENABLED = os.environ.get("OPENTELEMETRY_ENABLED", "false").lower() == "true"
OPENTELEMETRY_DEBUG = os.environ.get("OPENTELEMETRY_DEBUG", "false").lower() == "true"
OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "")
OTEL_SAMPLE_RATE = float(os.environ.get("OTEL_SAMPLE_RATE", "0.2"))
