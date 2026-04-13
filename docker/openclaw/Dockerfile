FROM node:22-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g openclaw@2026.3.2

# Install tool scripts (Python CLI tools called by ClawBot)
COPY openclaw/tools/ /usr/local/lib/claw-tools/
RUN chmod +x /usr/local/lib/claw-tools/*.py \
    && for f in /usr/local/lib/claw-tools/*.py; do \
         name=$(basename "$f" .py); \
         [ "$name" = "_api" ] && continue; \
         ln -s "$f" "/usr/local/bin/$name"; \
       done

USER node
WORKDIR /home/node
RUN mkdir -p .openclaw

EXPOSE 18789

CMD ["openclaw", "gateway", "run", "--bind", "lan", "--port", "18789"]
