"""API layer: JWT identity (auth), response intake (intake), decision wiring (decide).

The Lambda handler (mel.api.handler.lambda_handler) is owned by the integration agent and
calls these modules. Nothing here reads identity from a request body.
"""
