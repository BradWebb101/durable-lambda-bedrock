"""
Durable Lambda: Two-step Bedrock chain using the AWS Durable Execution SDK.

The SDK handles all checkpointing, replay, and Lambda-to-Lambda orchestration
automatically — no manual DynamoDB, SQS, or execution routing required.

Execution flow:
  - Invocation starts → SDK runs handler from top
  - context.step(bedrock_initial_analysis(...)) → executes, checkpoints result
  - Lambda may stop/restart here; SDK replays the handler and skips the
    completed step (returns the checkpointed result instantly)
  - context.step(bedrock_implementation_deep_dive(...)) → executes, checkpoints
  - Handler returns final dict → SDK marks execution complete

Caller flow:
  Invoke Lambda with {"message": "..."} → SDK returns execution status
  Poll via AWS SDK / ListDurableExecutions for completion + result
"""
import boto3

from aws_durable_execution_sdk_python import (
    DurableContext,
    StepContext,
    durable_execution,
    durable_step,
)
from system_prompt import SYSTEM_PROMPT

# ── AWS clients — initialised outside the handler for connection reuse ────────
bedrock = boto3.client("bedrock-runtime", region_name="eu-west-1")

MODEL_ID = "eu.anthropic.claude-sonnet-4-6"


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Initial Analysis
# ─────────────────────────────────────────────────────────────────────────────

@durable_step
def bedrock_initial_analysis(_step_ctx: StepContext, user_input: str) -> str:
    """
    Bedrock Call 1 — initial analysis of the user's request.
    Result is checkpointed by the SDK; skipped on handler replay.
    """
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "TASK 1 - INITIAL ANALYSIS\n\n"
                            f"Request: {user_input}\n\n"
                            "Provide a concise initial analysis covering: the core challenges, "
                            "key AWS services involved, and the top 3 risks to address."
                        )
                    }
                ],
            }
        ],
        inferenceConfig={"maxTokens": 512, "temperature": 0.1},
    )
    return response["output"]["message"]["content"][0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Implementation Deep Dive
# ─────────────────────────────────────────────────────────────────────────────

@durable_step
def bedrock_implementation_deep_dive(
    step_ctx: StepContext, user_input: str, first_result: str
) -> str:
    """
    Bedrock Call 2 — implementation detail based on Call 1's output.
    Receives the checkpointed first_result from the SDK, not DynamoDB.
    """
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "TASK 1 - INITIAL ANALYSIS\n\n"
                            f"Request: {user_input}\n\n"
                            "Provide a concise initial analysis covering: the core challenges, "
                            "key AWS services involved, and the top 3 risks to address."
                        )
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [{"text": first_result}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            "TASK 2 - IMPLEMENTATION DEEP DIVE\n\n"
                            "Based on your initial analysis above, provide:\n"
                            "1. A concrete CDK (TypeScript) snippet for the core infrastructure\n"
                            "2. A Python Lambda handler skeleton for the first pipeline stage\n"
                            "3. Specific data quality checks to implement at the Bronze layer\n"
                            "Be concise and production-focused."
                        )
                    }
                ],
            },
        ],
        inferenceConfig={"maxTokens": 768, "temperature": 0.1},
    )
    return response["output"]["message"]["content"][0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# Durable handler — orchestrates the two-step chain
# ─────────────────────────────────────────────────────────────────────────────

@durable_execution
def handler(event: dict, context: DurableContext) -> dict:
    """
    Durable Lambda entry point.

    The SDK replays this function on each Lambda invocation.  Completed steps
    return their checkpointed value instantly; pending steps execute and
    checkpoint before Lambda hands control back to the SDK runtime.
    """
    user_input = event.get(
        "message",
        "We are migrating our on-premise equity trade data pipeline to AWS. "
        "Outline the key architectural decisions and data quality considerations.",
    )

    first_result = context.step(bedrock_initial_analysis(user_input))
    second_result = context.step(bedrock_implementation_deep_dive(user_input, first_result))

    return {
        "call_1": first_result,
        "call_2": second_result,
    }
