# Ollama with SmolLM2 models pre-loaded
# Models: smollm2:135m (polling), smollm2:360m (complexity classification)
FROM ollama/ollama:latest

# Pre-pull models during build
RUN ollama serve & sleep 5 && \
    ollama pull smollm2:135m && \
    ollama pull smollm2:360m && \
    pkill ollama

EXPOSE 11434

CMD ["serve"]
