# Setup and Execution Guide

## 1. Prerequisites

- **Python:** `3.11` or higher (`3.11` to `3.14` supported)
- **API Keys (At least one required for capability judging):**
  - Google Gemini API Key (`GEMINI_API_KEY`) from [Google AI Studio](https://aistudio.google.com/)
  - Groq API Key (`GROQ_API_KEY`) from [Groq Console](https://console.groq.com/)
  - OpenRouter API Key (`OPENROUTER_API_KEY`) from [OpenRouter](https://openrouter.ai/)
  - Hugging Face Token (`HF_API_TOKEN`) from [HuggingFace Settings](https://huggingface.co/settings/tokens) (for CV structured extraction)

---

## 2. Environment Configuration

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Configure the required environment variables in `.env`:
   ```ini
   # Service Authentication (leave empty during local development)
   AI_SERVICE_API_KEY=

   # Primary Judge Provider (Google Gemini)
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_JUDGE_MODEL=gemini-3.8-flash

   # Secondary / Fallback Judge Providers
   GROQ_API_KEY=your_groq_api_key_here
   GROQ_JUDGE_MODEL=openai/gpt-oss-120b

   OPENROUTER_API_KEY=your_openrouter_api_key_here
   OPENROUTER_JUDGE_MODEL=meta-llama/llama-3.3-70b-instruct:free

   # CV Extraction Provider (Hugging Face)
   HF_API_TOKEN=your_huggingface_token_here

   # Caching Configuration (Process-local LRU)
   CACHE_TTL_SECONDS=3600
   CACHE_MAX_ENTRIES=128
   ```

---

## 3. Installation

From the `ai-service/` root directory:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install package in editable mode with development and UI dependencies
pip install -e ".[dev,ui]"
```

---

## 4. Running the Application

### A. Run the Flask REST API (Backend Service)
```bash
# Development server (Flask)
python -m app.main

# Production server (Gunicorn - Linux/Docker)
gunicorn --bind 0.0.0.0:8000 --workers 2 "app.main:create_app()"
```
The API is served by default at `http://localhost:8000`.

### B. Run the Streamlit Interactive UI
```bash
streamlit run ui/streamlit_app.py
```
The UI will open in your browser at `http://localhost:8501`.

---

## 5. Running the Test Suite

```bash
# Run all unit and integration tests with coverage report
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests only
pytest tests/integration/

# Run tests in verbose mode
pytest -v
```

---

## 6. Docker Deployment

### Run with Docker Compose:
```bash
docker-compose up --build
```

### Run standalone Docker container:
```bash
docker build -t amit-ai-service .
docker run -p 8000:8000 --env-file .env amit-ai-service
```
