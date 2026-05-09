build:
  rm -rf dist
  uv build

publish:
  uv publish --token $(<credentials/pypi_token)
  rm -rf dist

install:
  uv pip install -e .

# Docker image for the agent execution environment.
# Override the tag at invocation time, e.g. `just TAG=gemini-v2 publish-image`.
IMAGE := "ghcr.io/eceo902/benchmark_agent"
TAG := "gemini-v1"

build-image:
  cd agent_env && docker build --platform linux/amd64 -t {{IMAGE}}:{{TAG}} .

push-image:
  docker push {{IMAGE}}:{{TAG}}

verify-image:
  docker run --rm --platform linux/amd64 {{IMAGE}}:{{TAG}} gemini --version
  docker run --rm --platform linux/amd64 {{IMAGE}}:{{TAG}} grok --version

publish-image: build-image verify-image push-image
