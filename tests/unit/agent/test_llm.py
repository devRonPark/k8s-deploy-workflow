import unittest
from types import SimpleNamespace

from k8sagent.llm import AgentLLMClient, AgentLLMSettings, NoAuthHTTPChatClient
from k8sagent.models.intent import AgentKubernetesIntent, ComponentIntentSpec
from k8sagent.questions import Question


class FakeChatClient:
    def __init__(self, contents=None, error=None):
        self.contents = list(contents or [])
        self.error = error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


def client(contents=None, error=None) -> AgentLLMClient:
    return AgentLLMClient(
        AgentLLMSettings(
            base_url="http://llm.example/v1",
            model="test-model",
        ),
        client=FakeChatClient(contents, error),
    )


class AgentLLMTests(unittest.TestCase):
    def test_nl_to_changeset_returns_validated_changeset_and_forces_origin(self):
        llm = client(
            [
                '{"changes":[{"op":"set","path":"namespace","value":"prod"}],'
                '"origin":"wizard","summary":"set namespace"}'
            ]
        )
        cs = llm.nl_to_changeset(
            "set namespace",
            AgentKubernetesIntent(components=[ComponentIntentSpec(component_id="api", role="application")]),
            ["namespace"],
        )
        self.assertIsNotNone(cs)
        self.assertEqual(cs.origin, "nl_request")

    def test_disallowed_path_retries_then_none(self):
        llm = client(
            [
                '{"changes":[{"op":"set","path":"bad.path","value":"x"}],'
                '"origin":"nl_request","summary":"bad"}',
                '{"changes":[{"op":"set","path":"bad.path","value":"x"}],'
                '"origin":"nl_request","summary":"bad"}',
            ]
        )
        self.assertIsNone(llm.nl_to_changeset("bad", AgentKubernetesIntent(), ["namespace"]))
        self.assertEqual(len(llm._client.calls), 2)

    def test_broken_json_retries_then_none(self):
        llm = client(["not json", "also not json"])
        self.assertIsNone(llm.explain_analysis({"components": []}))
        self.assertEqual(len(llm._client.calls), 2)

    def test_code_fence_json_succeeds(self):
        llm = client(['```json\n{"text":"Use namespace prod"}\n```'])
        question = Question(
            id="Q-namespace",
            path="namespace",
            text="Namespace?",
            answer_type="k8s_name",
            severity="blocking",
        )
        self.assertEqual(llm.phrase_question(question), "Use namespace prod")

    def test_provider_exception_returns_none(self):
        llm = client(error=ConnectionError("down"))
        self.assertIsNone(llm.explain_analysis({"components": []}))

    def test_from_env_defaults_to_local_no_auth_endpoint(self):
        llm = AgentLLMClient.from_env(env={})
        self.assertIsNotNone(llm)
        self.assertEqual(llm.settings.base_url, "http://192.168.30.167:30000/v1")
        self.assertIsNone(llm.settings.model)

    def test_phrase_question_rejects_non_string_text(self):
        llm = client(['{"text": 3}'])
        question = Question(
            id="Q-namespace",
            path="namespace",
            text="Namespace?",
            answer_type="k8s_name",
            severity="blocking",
        )
        self.assertIsNone(llm.phrase_question(question))

    def test_payload_does_not_include_api_key(self):
        fake = FakeChatClient(['{"text":"ok"}'])
        llm = AgentLLMClient(
            AgentLLMSettings(
                base_url="http://llm.example/v1",
                model="test-model",
            ),
            client=fake,
        )
        llm.explain_analysis({"token": "metadata-name-only"})
        messages = str(fake.calls[0]["messages"])
        self.assertNotIn("Authorization", messages)

    def test_no_auth_http_client_discovers_model_and_sends_no_authorization(self):
        calls = []

        def transport(method, url, headers, body=None, timeout=30.0):
            calls.append((method, url, dict(headers), body))
            self.assertNotIn("Authorization", headers)
            self.assertEqual(headers, {"Content-Type": "application/json"})
            if method == "GET":
                return '{"data":[{"id":"local-model"}]}'
            return '{"choices":[{"message":{"content":"{\\"text\\":\\"ok\\"}"}}]}'

        chat = NoAuthHTTPChatClient(
            AgentLLMSettings(base_url="http://192.168.30.167:30000/v1"),
            transport=transport,
        )
        response = chat.chat.completions.create(
            model=None,
            messages=[{"role": "user", "content": "{}"}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        self.assertEqual(response.choices[0].message.content, '{"text":"ok"}')
        self.assertEqual(calls[0][0:2], ("GET", "http://192.168.30.167:30000/v1/models"))
        self.assertEqual(calls[1][0:2], ("POST", "http://192.168.30.167:30000/v1/chat/completions"))


if __name__ == "__main__":
    unittest.main()
