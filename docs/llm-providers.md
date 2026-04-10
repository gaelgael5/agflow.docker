# LLM Providers — llm_providers.json

## Types supportés (9)

`anthropic`, `openai`, `azure`, `google`, `mistral`, `ollama`, `groq`, `deepseek`, `moonshot`

## 17 providers pré-configurés

Claude Sonnet/Opus/Haiku, GPT-4o/Mini, Azure GPT-4o, Gemini Flash/Pro, Mistral Large, DeepSeek Chat/Coder, Kimi K2/K2.5, Groq Llama 70B, Ollama Llama3/Codestral/Qwen

## Throttling

- Par `env_key` (même clé API = même compteur)
- Sliding window 60s (RPM + TPM)
- 20 retries avec backoff exponentiel (×2, cap 120s)

## Utilisation par agent

`"llm": "claude-sonnet"` dans le registry. Override via env : `ARCHITECT_LLM=gpt-4o`
