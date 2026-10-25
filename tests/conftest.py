import pytest

# Tests are marked by the folder they live in, so a test can't silently run in the wrong tier.
_TIER_BY_DIR = {
    "unit": pytest.mark.unit,
    "integration": pytest.mark.integration,
    "e2e": pytest.mark.live,
}


def pytest_collection_modifyitems(items):
    for item in items:
        for part in item.path.parts:
            if part in _TIER_BY_DIR:
                item.add_marker(_TIER_BY_DIR[part])
                break
