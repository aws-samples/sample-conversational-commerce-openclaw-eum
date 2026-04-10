FROM node:22-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.3.2

USER node
WORKDIR /home/node
RUN mkdir -p .openclaw

EXPOSE 18789

CMD ["openclaw", "gateway", "run", "--bind", "lan", "--port", "18789"]
