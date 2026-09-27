FROM autoclip:local AS autoclip-build

FROM nginx:alpine

COPY --from=autoclip-build /app/frontend/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000
