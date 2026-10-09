FROM golang:1.24-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /server ./cmd/server && CGO_ENABLED=0 go build -o /worker ./cmd/worker
FROM alpine:3.21
RUN apk add --no-cache ca-certificates && adduser -D app
COPY --from=build /server /worker /usr/local/bin/
USER app
EXPOSE 8080
CMD ["server"]
