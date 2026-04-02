# Stage 1: Builder
FROM amazoncorretto:19 AS builder

WORKDIR /app

# Copy only Gradle wrapper + configs first for better caching
COPY build.gradle settings.gradle gradlew gradlew.bat ./
COPY gradle ./gradle

# Give execute permissions to Gradle wrapper
RUN chmod +x gradlew

# Pre-download dependencies
RUN ./gradlew downloadRepos || true

# Copy the rest of the source code
COPY . .

# Build the application
RUN ./gradlew clean installDist




# Stage 2: Final minimal image
FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

COPY --from=builder /app/build/install/hipstershop ./hipstershop

EXPOSE 9555

# Start server
ENTRYPOINT ["/app/hipstershop/bin/AdService"]