# NTD Simulator Web API

Runs NTD models in a Python/Flask backend web API, to be called by [NTD Simulator](https://github.com/ArtRabbitStudio/ntd-simulator).

### How to run

Install [pipenv](https://drive.google.com/drive/folders/1Or6lUkymYd_p031xKGZLcnTV4GYf-oYb) according to the instructions for your OS, then `cd` to the project directory and run:

```
$ pipenv install . # sets up per-project python environment ('env')
$ pipenv shell # starts a per-project shell using that env
```

Run in the shell during development:

```
(ntd-simulator-api) $ python flask_app.py # runs the app
```

Build & run in Docker container:

```
$ docker build -f Dockerfile -t <tag> .
$ docker run \
	--rm \
	-p 5000:5000 \
	-e GOOGLE_APPLICATION_CREDENTIALS=/app/service-account-key.json \
	-v ${PWD}/service-account-key.json:/app/service-account-key.json \
	<tag>
```
