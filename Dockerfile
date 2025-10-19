# Use Python 3.10 as the base
FROM python:3.10

# Install Supervisor
RUN apt-get update && apt-get install -y byobu supervisor \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /etc/supervisor/conf.d /app /tmp && \
    chown -R appuser:appuser /app /tmp /var/log/supervisor /var/run

# Create our working directory
WORKDIR /app

# Copy requirements.txt first, so Docker can cache the layer
COPY requirements.txt /app/

# Upgrade pip 
RUN pip install --no-cache-dir --upgrade pip


# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the supervisor config into the container
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Now copy the rest of the project
# (app.py, src folder, etc.)
COPY . /app/

# Ensure appuser owns everything
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the Flask port (if your app uses port 8080)
EXPOSE 8080

# Launch Supervisor in the foreground
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
