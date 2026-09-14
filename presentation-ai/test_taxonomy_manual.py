from app.taxonomy.canonicalize import canonicalize_property, is_known_claim_type

test_cases = ['Accuracy Rate', 'acc', 'Accuracy', 'some totally new metric']
for case in test_cases:
    print(f'{case!r} -> {canonicalize_property(case)!r}')

print('is_known_claim_type(performance):', is_known_claim_type('performance'))
print('is_known_claim_type(nonsense):', is_known_claim_type('nonsense'))
