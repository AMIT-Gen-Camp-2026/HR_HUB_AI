path = 'ui/streamlit_app.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()
content = content.replace('page_icon="favicon.svg", ', 'page_icon="🎯", ')
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed icon.')
