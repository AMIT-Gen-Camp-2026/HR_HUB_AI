path = 'config/settings.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

marker = 'hf_mode: Literal["local_transformers", "inference_api"] = "local_transformers"'
new_line = '\n    gemini_embedding_model: str = "gemini-embedding-001"'

if 'gemini_embedding_model' in content:
    print('Already present, skipping.')
elif marker in content:
    content = content.replace(marker, marker + new_line)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Inserted successfully.')
else:
    print('ERROR: marker line not found — file content differs from expected.')
