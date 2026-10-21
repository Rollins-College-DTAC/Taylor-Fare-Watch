"""The dashboard's cloud-mode GitHub calls, with a fake opener instead of the network."""

import io
import json
import urllib.error

import pytest

from agent.config import PROJECT_ROOT, load_paths
from dashboard.cloud import contents_request, dispatch_request, fetch_bytes, passcode_ok, send_dispatch
from dashboard.db import local_path


class FakeResponse(io.BytesIO):
    def __init__(self, body=b"", status=200):
        super().__init__(body)
        self.status = status


def test_contents_request_targets_the_data_branch_with_the_raw_media_type():
    req = contents_request("me/fare-watch", "exports/images/forecast.png", "tok")
    assert req.full_url == "https://api.github.com/repos/me/fare-watch/contents/exports/images/forecast.png?ref=data"
    assert req.get_header("Accept") == "application/vnd.github.raw+json"
    assert req.get_header("Authorization") == "Bearer tok"


def test_fetch_bytes_returns_content_and_none_for_a_missing_file():
    req = contents_request("me/fare-watch", "analytics.sqlite", "tok")
    assert fetch_bytes(req, opener=lambda r, timeout: FakeResponse(b"sqlite bytes")) == b"sqlite bytes"

    def not_found(r, timeout):
        raise urllib.error.HTTPError(r.full_url, 404, "Not Found", {}, None)

    assert fetch_bytes(req, opener=not_found) is None


def test_fetch_bytes_raises_on_other_errors():
    def unauthorized(r, timeout):
        raise urllib.error.HTTPError(r.full_url, 401, "Bad credentials", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        fetch_bytes(contents_request("me/fare-watch", "analytics.sqlite", "bad"), opener=unauthorized)


def test_dispatch_request_starts_review_yml_on_main_with_the_inputs():
    req = dispatch_request("me/fare-watch", "tok", "inc-1a2b3c4d", "released", "Pat")
    assert req.full_url == "https://api.github.com/repos/me/fare-watch/actions/workflows/review.yml/dispatches"
    assert req.get_method() == "POST"
    assert json.loads(req.data) == {
        "ref": "main", "inputs": {"incident_id": "inc-1a2b3c4d", "decision": "released", "reviewer": "Pat"},
    }
    send_dispatch(req, opener=lambda r, timeout: FakeResponse(status=204))
    with pytest.raises(RuntimeError):
        send_dispatch(req, opener=lambda r, timeout: FakeResponse(status=200))


def test_passcode_check():
    assert passcode_ok("s3cret", "s3cret")
    assert not passcode_ok("guess", "s3cret")
    assert not passcode_ok("", None)  # no configured passcode: nobody can review
    assert not passcode_ok("", "")


def test_local_paths_mirror_the_data_branch_layout():
    assert local_path("analytics.sqlite") == load_paths().sqlite
    assert local_path("generator_log.csv") == PROJECT_ROOT / "generator_log.csv"
    assert local_path("exports/images/forecast.png") == PROJECT_ROOT / "docs" / "images" / "forecast.png"
