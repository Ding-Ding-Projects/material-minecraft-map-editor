FROM nginx:1.27.4-alpine@sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html styles.css app.js theme.mjs regex-worker.mjs i18n.json search-surfaces.json site-config.json release-manifest.json articles.json /usr/share/nginx/html/
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD wget -q -O - http://127.0.0.1:8080/healthz | grep -q '"status":"ok"' || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
