FROM gradle:8-jdk21 AS build
WORKDIR /app
# force rebuild: flyway 11.8.0 explicit version
COPY build.gradle.kts settings.gradle.kts ./
COPY gradle gradle
RUN gradle dependencies --no-daemon -q || true
COPY src src
RUN gradle bootJar --no-daemon -x test

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
