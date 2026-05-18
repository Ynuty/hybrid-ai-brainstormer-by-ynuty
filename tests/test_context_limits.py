import pytest
from pydantic import ValidationError

from app.schemas import BrainstormRequest


def test_context_too_long_rejected():
    with pytest.raises(ValidationError):
        BrainstormRequest(topic="ok", context="x" * 90000)
