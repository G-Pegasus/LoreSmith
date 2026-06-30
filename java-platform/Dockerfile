FROM eclipse-temurin:21-jdk-alpine as build

WORKDIR /app

COPY pom.xml .
COPY src ./src

RUN apk add --no-cache maven && \
    mvn clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine

WORKDIR /app

COPY --from=build /app/target/java-platform-0.1.0.jar app.jar

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=10 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/api/v1/health || exit 1

ENTRYPOINT ["java", "-jar", "app.jar"]