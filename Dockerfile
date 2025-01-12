# Set base image (host OS)
FROM python:3.10

# Set the working directory in the container
WORKDIR /code

# Copy the dependencies file to the working directory
COPY requirements.txt .

# Install dependencies
RUN pip install -r requirements.txt

# Copy the content of the local src directory to the working directory
COPY src/ .

# Expose container's port 8080
EXPOSE 8080

# Command to run on container start
CMD [ "python", "./listener-db.py" ]
