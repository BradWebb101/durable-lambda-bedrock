"""
Standard Lambda: Two sequential Bedrock (Claude) calls.

Invocation 1 → Initial analysis (with large system prompt)
Invocation 2 → Deep dive / recommendations (conversation continuation)

Both calls happen inside a single Lambda execution — no checkpointing.
Returns timing, token counts, and both responses.
"""
import json
import time
import boto3
from system_prompt import SYSTEM_PROMPT

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"


def lambda_handler(event, context):
    # ── Parse input ──────────────────────────────────────────────────────────
    body = event
    if "body" in event and event["body"]:
        body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]

    user_input = body.get(
        "message",
        "We are migrating our on-premise equity trade data pipeline to AWS. "
        "Outline the key architectural decisions and data quality considerations.",
    )

    print(f"Standard Lambda - starting two sequential Bedrock calls")
    print(f"User input: {user_input[:120]}...")

    total_start = time.time()

    # ── Bedrock Call 1: Initial Analysis ─────────────────────────────────────
    call1_start = time.time()

    response1 = bedrock.converse(
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

    call1_duration = time.time() - call1_start
    first_result = response1["output"]["message"]["content"][0]["text"]
    first_usage = response1["usage"]

    print(
        f"Call 1 complete - {first_usage['inputTokens']} in / "
        f"{first_usage['outputTokens']} out tokens, {call1_duration:.2f}s"
    )

    # ── Bedrock Call 2: Deep Dive with conversation context ───────────────────
    call2_start = time.time()

    response2 = bedrock.converse(
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

    call2_duration = time.time() - call2_start
    second_result = response2["output"]["message"]["content"][0]["text"]
    second_usage = response2["usage"]

    print(
        f"Call 2 complete - {second_usage['inputTokens']} in / "
        f"{second_usage['outputTokens']} out tokens, {call2_duration:.2f}s"
    )

    total_duration = time.time() - total_start

    # ── Response ──────────────────────────────────────────────────────────────
    result = {
        "execution_type": "standard",
        "execution_model": "single_lambda_two_sequential_calls",
        "total_duration_seconds": round(total_duration, 3),
        "call_1": {
            "purpose": "initial_analysis",
            "duration_seconds": round(call1_duration, 3),
            "input_tokens": first_usage["inputTokens"],
            "output_tokens": first_usage["outputTokens"],
            "result": first_result,
        },
        "call_2": {
            "purpose": "implementation_deep_dive",
            "duration_seconds": round(call2_duration, 3),
            "input_tokens": second_usage["inputTokens"],
            "output_tokens": second_usage["outputTokens"],
            "result": second_result,
        },
        "totals": {
            "input_tokens": first_usage["inputTokens"] + second_usage["inputTokens"],
            "output_tokens": first_usage["outputTokens"] + second_usage["outputTokens"],
            "bedrock_calls": 2,
            "lambda_invocations": 1,
        },
    }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, indent=2),
    }
