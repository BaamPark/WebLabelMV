## Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . ./

# Allow overriding API base for /videos calls at build time
ARG REACT_APP_API_BASE=
ENV REACT_APP_API_BASE=$REACT_APP_API_BASE

RUN npm run build

## Runtime stage
FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/build /usr/share/nginx/html

# Custom nginx to proxy API to backend service
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3001

CMD ["nginx", "-g", "daemon off;"]

