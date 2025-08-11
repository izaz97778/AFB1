FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install ntpdate for time sync and required dependencies
RUN apt-get update && \
    apt-get install -y ntpdate gcc libffi-dev libssl-dev && \
    apt-get clean

# Sync time
RUN ntpdate -u pool.ntp.org

# Install Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY . /app

# Prevent .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Final run command with time sync again just in case
CMD ntpdate -u pool.ntp.org && python bot.py
