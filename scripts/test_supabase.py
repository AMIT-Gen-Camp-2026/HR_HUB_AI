import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.supabase_client import (
    SUPABASE_URL,
    fetch_lecturers,
    fetch_policies,
    get_data_chat_history,
    get_policy_chat_history,
    log_data_chat,
    log_policy_chat
)

print(f"Testing connection to Supabase: {SUPABASE_URL}")

print("\n1. Fetching Lecturers:")
lecturers = fetch_lecturers()
print(f"   Fetched {len(lecturers)} lecturers. (First: {lecturers[0]['name'] if lecturers else 'None'})")

print("\n2. Fetching Policies:")
policies = fetch_policies()
print(f"   Fetched {len(policies)} policies. (First: {policies[0]['title'] if policies else 'None'})")

print("\n3. Testing Chat Logging to Supabase:")
try:
    log_data_chat(
        question="Who are the available AI lecturers in Cairo?",
        answer="Found 2 matching lecturer(s): Ahmed Salah, Mona Ibrahim.",
        status="ok",
        filters_applied={"track": "AI", "city": "Cairo", "status": "available"},
        sources_count=2
    )
    print("   Logged test message to data_chat_messages successfully.")
except Exception as e:
    print(f"   Error logging to data_chat_messages: {e}")

try:
    log_policy_chat(
        question="What are the acceptance criteria for a new lecturer?",
        answer="The minimum requirement is 70% in demo video.",
        status="ok",
        citations=[{"doc": "Lecturer Evaluation Policy", "ref": "POL-01 §2"}],
        note="AI-generated"
    )
    print("   Logged test message to policy_chat_messages successfully.")
except Exception as e:
    print(f"   Error logging to policy_chat_messages: {e}")

print("\n4. Checking Chat History:")
data_hist = get_data_chat_history(5)
print(f"   Data chat messages in Supabase: {len(data_hist)}")

policy_hist = get_policy_chat_history(5)
print(f"   Policy chat messages in Supabase: {len(policy_hist)}")

print("\nSupabase Client test finished!")
