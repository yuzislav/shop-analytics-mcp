FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY server.py .
COPY shop.db .

# Set environment variables
ENV SHOP_DB_PATH=/app/shop.db

# Command to run the server
CMD ["python", "-u", "server.py"]
