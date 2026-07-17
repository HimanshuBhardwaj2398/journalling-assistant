"""Shared fakes for the agent test suite."""


class FakeLLMClient:
    """Scripted LLM client: pops responses in order, records every call.

    A response that is an Exception instance is raised instead of returned,
    so tests can script transport failures.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.max_tokens_seen = []

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.calls.append(messages)
        self.max_tokens_seen.append(max_tokens)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
