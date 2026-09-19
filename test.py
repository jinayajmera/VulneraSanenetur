import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
models = client.models.list()
for model in models.data:
    print(model.id)