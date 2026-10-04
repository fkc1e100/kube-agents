# The in-cluster POC Web Console for Kube-Agents.
# Provides a zero-config chat interface and incident feed for customer POCs.
#
# Build from repo root:
#   docker build -f cmd/web-console/Dockerfile -t ghcr.io/gke-labs/kube-agents/web-console:latest .

ARG GOLANG_IMAGE=golang
ARG GOLANG_VERSION=1.27-alpine
ARG DISTROLESS_IMAGE=gcr.io/distroless/static
ARG DISTROLESS_VERSION=nonroot

FROM ${GOLANG_IMAGE}:${GOLANG_VERSION} AS build
ENV GOTOOLCHAIN=local
WORKDIR /src/cmd/web-console
COPY cmd/web-console/go.mod ./
COPY cmd/web-console/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/web-console .

FROM ${DISTROLESS_IMAGE}:${DISTROLESS_VERSION}
COPY --from=build /out/web-console /web-console
USER nonroot
EXPOSE 8080
ENTRYPOINT ["/web-console"]
