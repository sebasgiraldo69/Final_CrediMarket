FROM node:22.20.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json index.html ./
COPY src ./src
# URL pública de MLflow para la ficha del modelo; no es un secreto.
ARG VITE_MLFLOW_URL=http://127.0.0.1:5000
ENV VITE_MLFLOW_URL=$VITE_MLFLOW_URL
RUN npm run build

FROM nginx:1.28.0-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
