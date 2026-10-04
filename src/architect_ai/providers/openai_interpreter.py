"""OpenAI Responses adapter. No tools, storage, retries or accepted project output."""

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from openai.types.responses import Response
from pydantic import ValidationError

from architect_ai.config import Settings
from architect_ai.providers.architectural_instructions import INSTRUCTION_VERSION, INSTRUCTIONS
from architect_ai.providers.openai_brief_schema import WireProposal, decode_proposal
from architect_ai.services.brief_contracts import (
    BriefRequest,
    InterpreterProviderError,
    ProviderErrorCode,
    ProviderInterpretation,
    ProviderMetadata,
)


class OpenAIArchitecturalInterpreterProvider:
    def __init__(self, settings: Settings, *, client: OpenAI | None = None) -> None:
        self.settings = settings
        self._client = client

    def interpret(self, request: BriefRequest) -> ProviderInterpretation:
        if len(request.model_dump_json()) > 60000:
            raise InterpreterProviderError(ProviderErrorCode.CONTEXT_TOO_LARGE)
        if self._client is None:
            secret = self.settings.openai_api_key
            if secret is None or not secret.get_secret_value().strip():
                raise InterpreterProviderError(ProviderErrorCode.MISSING_API_KEY)
            self._client = OpenAI(
                api_key=secret.get_secret_value(),
                max_retries=0,
                timeout=self.settings.openai_timeout_seconds,
            )
        try:
            raw = self._client.with_options(max_retries=0).responses.with_raw_response.parse(
                model=self.settings.openai_model,
                instructions=INSTRUCTIONS,
                input=request.model_dump_json(),
                text_format=WireProposal,
                store=False,
                tools=[],
                tool_choice="none",
                max_output_tokens=self.settings.openai_max_output_tokens,
                timeout=self.settings.openai_timeout_seconds,
            )
            # Check the typed API envelope before the SDK tries to parse possibly truncated text.
            envelope = Response.model_validate_json(raw.http_response.text)
            if any(
                content.type == "refusal"
                for item in envelope.output
                if item.type == "message"
                for content in item.content
            ):
                raise InterpreterProviderError(ProviderErrorCode.REFUSAL)
            if envelope.status == "incomplete":
                raise InterpreterProviderError(ProviderErrorCode.INCOMPLETE_RESPONSE)
            if envelope.status != "completed":
                raise InterpreterProviderError(ProviderErrorCode.TRANSIENT_FAILURE)
            response = raw.parse()
            if response.output_parsed is None:
                raise InterpreterProviderError(ProviderErrorCode.INVALID_RESPONSE)
            proposal = decode_proposal(response.output_parsed, request)
            return ProviderInterpretation(
                proposal=proposal,
                metadata=ProviderMetadata(
                    provider="openai",
                    model=self.settings.openai_model,
                    response_id=response.id,
                    instruction_version=INSTRUCTION_VERSION,
                ),
            )
        except (AuthenticationError, PermissionDeniedError):
            raise InterpreterProviderError(ProviderErrorCode.AUTHENTICATION_FAILED) from None
        except RateLimitError:
            raise InterpreterProviderError(ProviderErrorCode.RATE_LIMITED) from None
        except (BadRequestError, NotFoundError):
            raise InterpreterProviderError(ProviderErrorCode.UNSUPPORTED_CONFIGURATION) from None
        except LengthFinishReasonError:
            raise InterpreterProviderError(ProviderErrorCode.INCOMPLETE_RESPONSE) from None
        except ContentFilterFinishReasonError:
            raise InterpreterProviderError(ProviderErrorCode.REFUSAL) from None
        except (ValidationError, ValueError, APIResponseValidationError):
            raise InterpreterProviderError(ProviderErrorCode.INVALID_RESPONSE) from None
        except APIStatusError as error:
            code = (
                ProviderErrorCode.TRANSIENT_FAILURE
                if error.status_code >= 500
                else ProviderErrorCode.UNSUPPORTED_CONFIGURATION
            )
            raise InterpreterProviderError(code) from None
        except (APIConnectionError, APIError):
            raise InterpreterProviderError(ProviderErrorCode.TRANSIENT_FAILURE) from None
