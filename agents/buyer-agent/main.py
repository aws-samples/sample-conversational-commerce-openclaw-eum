"""FastAPI server for the buyer agent — deployed to AgentCore Runtime."""

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from agent import create_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


@app.get("/ping")
def ping():
    return {"status": "healthy"}


@app.post("/invocations")
async def invocations(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    session_id = body.get("session_id", "default")

    if not prompt:
        return JSONResponse(status_code=400, content={"error": "prompt is required"})

    try:
        agent = create_agent(session_id)
        result = agent(prompt)
        response_text = result.message["content"][0]["text"]
        return {"response": response_text}
    except Exception as e:
        logger.exception("Agent invocation failed")
        return JSONResponse(status_code=500, content={"error": str(e)})
