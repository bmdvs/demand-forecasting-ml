"""dfm.config carries the extract generator's calendar and lot constants unchanged."""
from data_source.generate import config as G

from dfm import config as C


def test_constants_match_the_generator():
    for name in ["FORWARD_START", "END_DATE", "AS_OF_DATE", "ORDER_COVER_DAYS"]:
        assert getattr(C, name) == getattr(G, name), name
