from app.taxonomy.canonicalize import canonicalize_property, is_known_claim_type


def test_known_alias_maps_to_canonical():
    assert canonicalize_property("Accuracy Rate") == "accuracy"
    assert canonicalize_property("acc") == "accuracy"


def test_unknown_alias_passes_through_unchanged():
    assert canonicalize_property("some totally new metric") == "some totally new metric"


def test_claim_type_validation():
    assert is_known_claim_type("performance") is True
    assert is_known_claim_type("nonsense") is False
