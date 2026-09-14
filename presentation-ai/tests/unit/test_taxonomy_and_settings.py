from app.taxonomy.canonicalize import canonicalize_property, is_known_claim_type


def test_canonicalize_known_aliases():
    assert canonicalize_property('Accuracy Rate') == 'accuracy'
    assert canonicalize_property('acc') == 'accuracy'
    assert canonicalize_property('دقة') == 'accuracy'


def test_canonicalize_unknown_passthrough():
    assert canonicalize_property('totally new metric') == 'totally new metric'


def test_claim_type_validation():
    assert is_known_claim_type('performance') is True
    assert is_known_claim_type('nonsense') is False
