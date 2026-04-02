# Ad Service

The Ad service provides advertisement based on context keys. If no context keys are provided then it returns random ads.

## Building locally

The Ad Service requires Java 19 (OpenJDK / Amazon Corretto) to build and it uses Gradle wrapper to compile, install, and run. Gradle wrapper is already included in the repo, so you don’t need to install Gradle separately.

```
./gradlew installDist
```
It will create executable script src/adservice/build/install/hipstershop/bin
To run the service, navigate to the bin folder:-
```
./AdService.bat
```

to run the client-
```
./AdServiceClient.bat
```

### Upgrading gradle version
If you need to upgrade the version of gradle then run

```
./gradlew wrapper --gradle-version <new-version>
```

## Running with Docker

If you prefer running the Ad Service in a container, you can do the following:

```
docker build -t adservice:latest .
```
Run the container:

```
docker run -p 9555:9555 adservice:latest
```

## Notes
- Google Java Format checks are skipped during installDist, so you won’t see formatting errors blocking your build.

- Using installDist or the custom Gradle tasks is the recommended way to run this service locally.