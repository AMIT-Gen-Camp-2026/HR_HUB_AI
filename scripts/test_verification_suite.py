import sys
import os
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# Reconfigure stdout to utf-8 if possible
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

print("=" * 70)
print("🚀 RUNNING AUTOMATED VERIFICATION SUITE FOR HR AI ASSISTANT")
print("=" * 70)

# ---------------------------------------------------------------------------
# TEST GROUP 1: DATA QUERIES
# ---------------------------------------------------------------------------
print("\n" + "=" * 50)
print("PART 1: TESTING DATA QUERIES (/api/chat_data)")
print("=" * 50)

data_test_cases = [
    {
        "name": "1. Track + City + Availability (Available AI in Cairo)",
        "payload": {"question": "Who are the available AI lecturers in Cairo?"},
        "expected_status": "ok",
        "min_sources": 2,
        "check_names": ["menna sallam", "Dr. Tarek Mahmoud"]
    },
    {
        "name": "2. Networks Track",
        "payload": {"question": "Show all Networks lecturers"},
        "expected_status": "ok",
        "min_sources": 3,
        "check_names": ["ahmed", "Mary Valentine", "Chantale Dickson"]
    },
    {
        "name": "3. Testing Track",
        "payload": {"question": "Who are the testing instructors?"},
        "expected_status": "ok",
        "min_sources": 2,
        "check_names": ["Sarah Jenkins", "osama"]
    },
    {
        "name": "4. Full-Stack Track via 'software'",
        "payload": {"question": "Show software developers in Alexandria"},
        "expected_status": "ok",
        "min_sources": 1,
        "check_names": ["Omar Khaled"]
    },
    {
        "name": "5. Skills Filter Combined with City and Status",
        "payload": {"question": "Available instructors who know Python in Cairo"},
        "expected_status": "ok",
        "min_sources": 3,
        "check_names": ["menna sallam", "Dr. Tarek Mahmoud"]
    },
    {
        "name": "6. Specific Lecturer Contact Info",
        "payload": {"question": "What is Dr. Tarek's contact details?"},
        "expected_status": "ok",
        "min_sources": 1,
        "check_names": ["Dr. Tarek Mahmoud"]
    },
    {
        "name": "7. Experience Filtering (> 5 years in AI)",
        "payload": {"question": "Who has more than 5 years of experience in AI?"},
        "expected_status": "ok",
        "min_sources": 1,
        "check_names": ["mazen Mohamed Mahmoud Ahmed Mohamed ElBanna"]
    },
    {
        "name": "8. Most Experienced Ranking",
        "payload": {"question": "Who is the most experienced instructor?"},
        "expected_status": "ok",
        "min_sources": 5,
        "check_names": ["Brittany Short"]
    },
    {
        "name": "9. Out of Scope (General Knowledge)",
        "payload": {"question": "What is the capital of France?"},
        "expected_status": "out_of_scope",
        "min_sources": 0,
        "check_names": []
    },
    {
        "name": "10. Out of Scope (Cooking Recipe)",
        "payload": {"question": "How do I make chocolate cake?"},
        "expected_status": "out_of_scope",
        "min_sources": 0,
        "check_names": []
    }
]

data_passes = 0
for tc in data_test_cases:
    print(f"\n[TEST] {tc['name']}")
    resp = client.post("/api/chat_data", json=tc["payload"])
    assert resp.status_code == 200, f"HTTP Error: {resp.status_code}"
    data = resp.json()
    
    status = data.get("status")
    sources = data.get("sources", [])
    answer = data.get("answer", "")
    
    print(f"  Status: {status} (Expected: {tc['expected_status']})")
    print(f"  Sources Count: {len(sources)}")
    print(f"  Answer Preview: {answer[:120]}...")
    
    assert status == tc["expected_status"], f"Expected status {tc['expected_status']}, got {status}"
    if tc["expected_status"] == "ok":
        assert len(sources) >= tc["min_sources"], f"Expected at least {tc['min_sources']} sources, got {len(sources)}"
        for name in tc["check_names"]:
            assert any(name.lower() in s["name"].lower() for s in sources), f"Name '{name}' missing from sources!"
    elif tc["expected_status"] == "out_of_scope":
        assert len(sources) == 0, f"Out of scope query should return 0 sources, got {len(sources)}"
        assert "outside the scope" in answer.lower(), "Expected out of scope refusal in answer!"
        
    print("  -> PASSED! \u2705")
    data_passes += 1

# Multi-turn test for data chat
print("\n[TEST] 11. Multi-turn Follow-up in Data Chat")
session_id_data = None

# Turn 1
r1 = client.post("/api/chat_data", json={"question": "Show available AI instructors in Cairo"})
d1 = r1.json()
session_id_data = d1["session_id"]
assert len(d1["sources"]) >= 2
print(f"  Turn 1 returned {len(d1['sources'])} instructors in Cairo.")

# Turn 2: Follow-up referencing "them"
r2 = client.post("/api/chat_data", json={"question": "Which of them has the most experience?", "session_id": session_id_data})
d2 = r2.json()
assert d2["status"] == "ok"
# Among Cairo AI available: mazen has 10y, Tarek has 5y, menna has 3y -> top is mazen
assert any("mazen" in s["name"].lower() for s in d2["sources"])
print(f"  Turn 2 successfully identified top experienced from previous turn ({d2['sources'][0]['name']} - {d2['sources'][0]['experience_years']} yrs).")
print("  -> PASSED! \u2705")
data_passes += 1


# ---------------------------------------------------------------------------
# TEST GROUP 2: POLICIES & REGULATIONS
# ---------------------------------------------------------------------------
print("\n" + "=" * 50)
print("PART 2: TESTING POLICY QUERIES (/api/chat_policy)")
print("=" * 50)

policy_test_cases = [
    {
        "name": "1. Working Hours & Attendance Policy",
        "payload": {"question": "What are the rules for working hours and attendance?"},
        "expected_status": "ok",
        "min_citations": 1,
        "keywords_in_answer": ["Working Hours", "Attendance"]
    },
    {
        "name": "2. Travel Expenses Policy",
        "payload": {"question": "What is the policy on travel expenses and advances?"},
        "expected_status": "ok",
        "min_citations": 1,
        "keywords_in_answer": ["Travel"]
    },
    {
        "name": "3. Disciplinary Measures Policy",
        "payload": {"question": "What are the disciplinary measures for misconduct?"},
        "expected_status": "ok",
        "min_citations": 1,
        "keywords_in_answer": ["Disciplinary", "Violations"]
    },
    {
        "name": "4. Artificial Intelligence & Automated Decision Policy",
        "payload": {"question": "What are the guidelines for using Artificial Intelligence and automated decision support?"},
        "expected_status": "ok",
        "min_citations": 1,
        "keywords_in_answer": ["Artificial Intelligence"]
    },
    {
        "name": "5. Hybrid Work Policy (Direct Substantive Retrieval)",
        "payload": {"question": "tell me about Hybrid Work"},
        "expected_status": "ok",
        "min_citations": 1,
        "keywords_in_answer": ["Hybrid Work", "three days per week", "on-site coverage"]
    },
    {
        "name": "6. Out of Scope Policy Question (Unrelated Cooking)",
        "payload": {"question": "How to make homemade pizza dough?"},
        "expected_status": "not_covered",
        "min_citations": 0,
        "keywords_in_answer": ["not covered"]
    }
]

policy_passes = 0
for tc in policy_test_cases:
    print(f"\n[TEST] {tc['name']}")
    resp = client.post("/api/chat_policy", json=tc["payload"])
    assert resp.status_code == 200, f"HTTP Error: {resp.status_code}"
    data = resp.json()
    
    status = data.get("status")
    citations = data.get("citations", [])
    answer = data.get("answer", "")
    
    print(f"  Status: {status} (Expected: {tc['expected_status']})")
    print(f"  Citations Count: {len(citations)}")
    if citations:
        for c in citations[:2]:
            print(f"    - [{c.get('ref')}] {c.get('doc')}")
    print(f"  Answer Preview: {answer[:140]}...")
    
    assert status == tc["expected_status"], f"Expected status {tc['expected_status']}, got {status}"
    if tc["expected_status"] == "ok":
        assert len(citations) >= tc["min_citations"], f"Expected at least {tc['min_citations']} citations, got {len(citations)}"
        # Check citations format
        for c in citations:
            assert "ref" in c and "doc" in c and "text" in c
            assert len(c["ref"]) > 0
        if "keywords_in_answer" in tc:
            for kw in tc["keywords_in_answer"]:
                assert kw.lower() in answer.lower(), f"Keyword '{kw}' missing from answer!"
    elif tc["expected_status"] == "not_covered":
        assert "not covered" in answer.lower(), "Expected 'not covered' in answer!"

    print("  -> PASSED! \u2705")
    policy_passes += 1

# Multi-turn test for policy chat
print("\n[TEST] 7. Multi-turn Follow-up in Policy Chat")
# Turn 1
r1 = client.post("/api/chat_policy", json={"question": "What are the rules for travel and business events?"})
d1 = r1.json()
session_id_policy = d1["session_id"]
assert d1["status"] == "ok"
print(f"  Turn 1 retrieved {len(d1['citations'])} citations on travel.")

# Turn 2: Follow-up
r2 = client.post("/api/chat_policy", json={"question": "What about travel expenses and reimbursement?", "session_id": session_id_policy})
d2 = r2.json()
assert d2["status"] == "ok"
assert len(d2["citations"]) >= 1
print(f"  Turn 2 retrieved {len(d2['citations'])} citations on travel expenses.")
print("  -> PASSED! \u2705")
policy_passes += 1

print("\n" + "=" * 70)
print(f"🎉 ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
print(f"   Data Queries:   {data_passes}/11 tests passed")
print(f"   Policy Queries: {policy_passes}/7 tests passed")
print("=" * 70)
