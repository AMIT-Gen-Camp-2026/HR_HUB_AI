# Scripts

One-off and operational scripts. Anything that runs regularly belongs in `app/` or `eval/`.

مفيش scripts فعلية دلوقتي - `check_env.py` القديم اتشال لأنه كان بيعتمد
على provider abstraction (`app/providers/factory.py`) اتشال ضمن تنضيف
المسار المش شغال، و`make_fixture_cv.py` المذكور هنا قبل كده معملش خالص.

لو محتاجين حاجة زي `check_env.py` تاني (فحص إن HF_API_TOKEN شغال قبل
ما تضيّع وقت في debugging)، أسهل حاجة:
`python -c "from config.settings import config; config.validate()"`
من جوه `ai-service/`.
