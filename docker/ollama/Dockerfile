# Ollama with Ministral for routing
FROM ollama/ollama:latest

# Pre-pull model during build
RUN ollama serve & sleep 5 && \
    ollama pull ministral-3:3b-instruct-2512-fp16 && \
    pkill ollama

EXPOSE 11434

CMD ["serve"]
