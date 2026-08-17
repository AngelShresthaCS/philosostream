# Use an official, lightweight Python image as the base OS
FROM python:3.11-slim

# Prevent Python from writing useless .pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure console output is not buffered by Docker (so you can see live logs)
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy ONLY the requirements file first to leverage Docker's caching layer.
# (If your dependencies don't change, Docker skips reinstalling them on rebuilds)
COPY backend/requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your backend code into the container
COPY backend/ .

# Expose the port that FastAPI will run on
EXPOSE 8000

# Start the Uvicorn server 
# Note: Adjust "app.main:app" if your main FastAPI instance is located elsewhere
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]