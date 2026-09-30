FROM golang:1.25-alpine@sha256:1ae0735f00daffa3aaf1363a5184c0d2dc55c78e3db4ec70241cdac97bf84b59 AS navigatorr-builder

ARG NAVIGATORR_REPOSITORY=https://github.com/JakeNesler/navigatorr.git
ARG NAVIGATORR_REF=45e22ee02ad6b09d27be121d6f31842471545e5a

RUN apk add --no-cache ca-certificates git
RUN git clone --filter=blob:none "${NAVIGATORR_REPOSITORY}" /src \
    && git -C /src checkout --detach "${NAVIGATORR_REF}"
WORKDIR /src
RUN mkdir -p /out \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/navigatorr .

FROM python:3.13-alpine@sha256:79e7a9b9ff1cbceff819f856fb374477792a5967759d94df266de7b7b4120e6f

ARG MCP_STDIO_VERSION=0.43.6

ENV HOME=/var/lib/navigatorr \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache ca-certificates \
    && pip install --no-cache-dir "mcp-stdio==${MCP_STDIO_VERSION}" \
    && addgroup -g 10001 navigatorr \
    && adduser -D -H -u 10001 -G navigatorr navigatorr \
    && mkdir -p /var/lib/navigatorr \
    && chown -R navigatorr:navigatorr /var/lib/navigatorr

COPY --from=navigatorr-builder /out/navigatorr /usr/local/bin/navigatorr

USER 10001:10001
EXPOSE 8080

ENTRYPOINT ["mcp-stdio"]
CMD ["--help"]
