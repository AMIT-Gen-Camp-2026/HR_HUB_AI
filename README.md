# Internal HR AI Assistant — Chatbot (Supabase Enabled)

A modern FastAPI chatbot application with a dual-page interface connected to **Supabase PostgreSQL**:
1. **Data Queries**: Natural language search across lecturer profiles (track, location, availability, experience, skills).
2. **Policies & Regulations**: Semantic RAG search across company policies with exact citations.

---

## 🗄️ Supabase Setup & Database Tables

The project includes a complete SQL schema and dummy data script: [`supabase_schema.sql`](file:///d:/downloads/hr_ai_assistant/hr_ai_assistant/supabase_schema.sql).

### Tables Created:
1. `lecturers`: Stores lecturer profiles, track specializations, city, contact info, status, experience years, and skills array.
2. `policies`: Stores internal policy documents (`POL-01` to `POL-04`) and paragraph references.
3. `data_chat_messages`: Logs conversation history and query analytics for **Page 1 (Data Queries)**.
4. `policy_chat_messages`: Logs conversation history, citations, and status for **Page 2 (Policies & Regulations)**.

### How to Apply the Schema in Supabase:
1. Open your [Supabase Dashboard SQL Editor](https://supabase.com/dashboard/project/giwwiktvxwvtdasorpwj/sql/new).
2. Copy the entire contents of [`supabase_schema.sql`](file:///d:/downloads/hr_ai_assistant/hr_ai_assistant/supabase_schema.sql).
3. Click **Run**.
4. All tables, Row Level Security (RLS) policies, and dummy data will be created instantly.

---

## 🚀 Quickstart

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open your browser at: **http://127.0.0.1:8000**

---

## 📁 Project Structure

```
hr_ai_assistant/
├── app/
│   ├── main.py              # FastAPI endpoints (data queries, policy RAG, history)
│   └── supabase_client.py   # Supabase REST client (fetch records & log chat history)
├── data/
│   ├── lecturers.json       # Local fallback lecturer data
│   └── policies.json        # Local fallback policy documents
├── static/
│   └── index.html           # 2-Page interactive Chatbot frontend
├── scripts/
│   └── test_supabase.py     # Connectivity & diagnostic test script
├── supabase_schema.sql      # Supabase SQL schema + RLS policies + dummy data
├── requirements.txt         # Dependencies
└── README.md                # Documentation
```
