from app.prompts.registry import PromptRegistry
from config.settings import get_settings

registry = PromptRegistry(get_settings().prompts_dir)
print('Loaded templates count:', len(registry))

rendered = registry.render('claim_extract', slide_number=1, slide_text='Our model achieved 95 percent accuracy.')
print('Rendered length:', len(rendered))
print('Contains slide text:', 'Our model achieved 95 percent accuracy.' in rendered)
