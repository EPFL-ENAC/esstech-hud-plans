FROM node:20-alpine AS build-stage

WORKDIR /app
ARG APP_MODE=pwa
COPY package*.json ./
COPY . .
RUN npm ci
RUN case "$APP_MODE" in \
      pwa) npm run build:pwa ;; \
      spa) npm run build ;; \
      *) echo "APP_MODE must be pwa or spa" >&2; exit 1 ;; \
    esac && cp -R "dist/$APP_MODE" /app/site

FROM nginx:stable-alpine AS production-stage
RUN mkdir /app
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build-stage /app/site /app
EXPOSE 80

RUN apk add --no-cache bash
COPY entrypoint.sh /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
