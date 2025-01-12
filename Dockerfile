# Use Python 3.10 as the base
FROM python:3.10

# Install Supervisor
RUN apt-get update && apt-get install -y supervisor \
    && rm -rf /var/lib/apt/lists/*

# Create a directory for Supervisor configs
RUN mkdir -p /etc/supervisor/conf.d

# Create our working directory
WORKDIR /app

# Copy requirements.txt first, so Docker can cache the layer
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the supervisor config into the container
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Now copy the rest of the project
# (app.py, src folder, etc.)
COPY . /app/

# Expose the Flask port (if your app uses port 8080)
EXPOSE 8080

# Launch Supervisor in the foreground
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
