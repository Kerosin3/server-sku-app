"""
The only module that knows which model is behind the agent.

Everything else — the tools, the prompt, the loop — works against
LangChain's chat interface and cannot tell a local model from a hosted
one. That is deliberate: the plan is to develop against the local model
and move to a hosted one later, and the move should be a change of
environment variable rather than a change of code.

Be clear about what that portability does and does not cover. The wiring
moves for free; behaviour does not. A prompt padded with reminders for a
weaker model is merely wasteful on a stronger one, but a terse prompt
tuned on a strong model tends to fall apart on a weak one — so develop
against the weaker of the two and the direction of travel is safe.

Provider packages are imported inside the branches on purpose: only the
provider actually in use has to be installed, so the local setup does
not drag in an SDK for a service it never calls.
"""
import os

MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "local")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen36-claude47:latest")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

# Tool choice is a decision, not a piece of writing. Sampling variety
# here buys nothing and costs correctness: the same question should pick
# the same tool with the same arguments every time.
TEMPERATURE = float(os.environ.get("MODEL_TEMPERATURE", "0"))


def build_model():
    """Return a chat model with tool calling, per MODEL_PROVIDER."""
    if MODEL_PROVIDER == "local":
        from langchain_ollama import ChatOllama

        # reasoning=False turns off the model's thinking mode. Qwen3 has
        # one, and with it on the tool arguments picked up junk — a
        # comment of "замена вентилятора" arriving as notes=-2026, over
        # and over. Thinking earns its keep on open-ended questions; this
        # agent's job is to pick the right call and fill in fields it was
        # handed, which is not that kind of problem.
        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_URL,
            temperature=TEMPERATURE,
            reasoning=False,
        )

    if MODEL_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic  # pip install langchain-anthropic

        return ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            temperature=TEMPERATURE,
        )

    if MODEL_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI  # pip install langchain-openai

        return ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4o"), temperature=TEMPERATURE)

    raise SystemExit(
        f"MODEL_PROVIDER={MODEL_PROVIDER!r} is not one of: local, anthropic, openai."
    )


def describe() -> str:
    if MODEL_PROVIDER == "local":
        return f"{OLLAMA_MODEL} через Ollama ({OLLAMA_URL})"
    return f"{MODEL_PROVIDER}"
