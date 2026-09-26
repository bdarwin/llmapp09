import os

# Never ship traces from the unit tests: they use a mocked HTTP client, so the
# resulting traces are meaningless and would pollute the Langfuse project.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
