"""Build-only placeholder; never installed into the application's mel directory."""
from bedrock_agentcore.runtime import BedrockAgentCoreApp

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    return {"status": "stub"}


if __name__ == "__main__":
    app.run()
