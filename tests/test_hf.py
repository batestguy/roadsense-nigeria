from __future__ import annotations

import json

import pytest

from roadsense import config, hf


def test_resolve_url_points_at_the_public_dataset_file():
    url = hf.resolve_url("corridors.parquet")
    assert url == (
        "https://huggingface.co/datasets/roadsense-ng/nigeria-roads/resolve/main/corridors.parquet"
    )


def test_resolve_url_accepts_an_override_repo_and_revision():
    url = hf.resolve_url("x.parquet", repo_id="someone/else", revision="v1")
    assert url == "https://huggingface.co/datasets/someone/else/resolve/v1/x.parquet"


def test_describe_covers_every_published_table():
    described = hf.describe()
    assert set(described["files"]) == set(config.PUBLISHED_TABLES)
    for entry in described["files"].values():
        assert entry["url"].startswith("https://huggingface.co/datasets/")
        assert entry["url"].endswith(entry["file"])


def test_token_error_names_the_missing_variable(monkeypatch):
    monkeypatch.delenv(hf.TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        hf.token()


def test_token_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv(hf.TOKEN_ENV, "hf_example")
    assert hf.token() == "hf_example"


def test_write_description_round_trips(tmp_path):
    dest = hf.write_description(tmp_path / "manifest.json")
    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["repo"] == config.HF_DATASET_REPO
