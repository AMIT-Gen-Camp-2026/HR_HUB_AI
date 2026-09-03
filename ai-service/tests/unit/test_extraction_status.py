from app.pipeline.run import extraction_status
from app.schemas.cv import CVSchema


def test_empty_successful_extraction_is_distinct_from_success() -> None:
    assert extraction_status(CVSchema()) == "EMPTY"
    assert extraction_status(CVSchema(skills=["Python"])) == "SUCCESS"
