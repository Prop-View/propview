FROM node:22.14.0-alpine3.21 AS build

WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
ARG VITE_API_URL=http://localhost:8001
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.27.4-alpine
COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
