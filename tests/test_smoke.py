"""Smoke test: package imports. Real behaviour lands in later steps."""
import pytest

import ingestor


def test_package_importable() -> None:
    assert ingestor is not None


@pytest.mark.xfail(reason="Bronze ingestor not implemented yet — placeholder for step 1.3+")
def test_end_to_end_ingest_placeholder() -> None:
    raise NotImplementedError
