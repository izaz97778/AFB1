FROM python:3.11-slim

WORKDIR /app

# Install required packages
RUN apt-get update && \
    apt-get install -y gcc libffi-dev libssl-dev ntpdate && \
    apt-get clean

# Install Python dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY . /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Use shell to ignore ntpdate error if time can't be set
CMD ntpdate -u pool.ntp.org || true && python bot.py
