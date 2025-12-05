FROM python:3.12-slim

# Install uv for mcp-background-job
RUN pip install --no-cache-dir uv

# Set working directory
WORKDIR /app

# Install bridge dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Run uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
