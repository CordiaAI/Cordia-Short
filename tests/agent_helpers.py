"""Only the external chat-model boundary is scripted; the graph remains real."""
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedModel(BaseChatModel):
    replies: list = Field(default_factory=list)
    requests: list = Field(default_factory=list)
    callback: object = None

    @property
    def _llm_type(self):
        return "scripted-test-boundary"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.requests.append(list(messages))
        reply = self.callback(messages) if self.callback else self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=reply)])


def call(name, **args):
    return AIMessage(content="", tool_calls=[{
        "name": name, "args": args, "id": "call-1", "type": "tool_call",
    }])
