from app.schemas.presentation import ClaimVerification

# Test 1: empty reason must be rejected
for bad in ['', '   ', '\n\t']:
    try:
        v = ClaimVerification(claim_id='x', status='plausibility_flag', confidence=0.5, reason=bad)
        print('BUG: empty/whitespace reason was accepted:', repr(bad))
    except Exception:
        print('OK: correctly rejected:', repr(bad))

# Test 2: valid reason must pass
v = ClaimVerification(claim_id='x', status='plausibility_flag', confidence=0.5, reason='This is a real reason.')
print('OK: valid reason accepted:', v.reason)
