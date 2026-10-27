"""Safety guards: staging-only writes, rate limiting, disabled portal."""
import pytest

from iris_spv.load import Db, Loader, clean_pg_url
from iris_spv.ratelimit import RateLimitExceeded, RateLimiter
from iris_spv.sources import get_source
from iris_spv.sources.portal import PortalDisabled


def test_loader_refuses_non_staging_schema():
    db = Db("sqlite:///:memory:")
    for schema in ("iris_core", "public", ""):
        with pytest.raises(ValueError, match="only 'iris_staging'"):
            Loader(db, schema)


def test_rate_limiter_blocks_after_limit_and_recovers():
    t = [0.0]
    limiter = RateLimiter(max_per_hour=3, clock=lambda: t[0])
    for _ in range(3):
        limiter.acquire()
    with pytest.raises(RateLimitExceeded):
        limiter.acquire()
    t[0] = 3601                         # an hour later the window has passed
    limiter.acquire()


def test_portal_is_disabled_by_default():
    with pytest.raises(PortalDisabled):
        list(get_source("portal").fetch())


def test_export_source_requires_a_path():
    with pytest.raises(ValueError):
        get_source("export")


@pytest.mark.parametrize("url, expected", [
    ("postgresql+psycopg2://u:p@host:5433/db", "postgresql://u:p@host:5433/db"),   # SQLAlchemy style
    ("postgresql+psycopg://u:p@host/db", "postgresql://u:p@host/db"),
    ("postgresql://u:p@host/db", "postgresql://u:p@host/db"),                      # already plain
])
def test_sqlalchemy_style_database_url_is_accepted(url, expected):
    assert clean_pg_url(url) == expected
