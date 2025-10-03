"""Helper functions for LLM"""

import json
from pydantic import BaseModel
from src.llm.models import get_model, get_model_info
from src.utils.progress import progress
from src.graph.state import AgentState
from src.data.llm_response_cache import get_llm_cache


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.
    Uses persistent cache with 7-day freshness check to avoid redundant API calls.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """

    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name = "gpt-4.1"
        model_provider = "OPENAI"

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, 'api_keys'):
            api_keys = request.api_keys

    # Import ModelProvider enum
    from src.llm.models import ModelProvider

    # Convert string to ModelProvider enum if needed
    if isinstance(model_provider, str):
        try:
            model_provider_enum = ModelProvider(model_provider.upper())
        except ValueError:
            print(f"Invalid model provider: {model_provider}, using OPENAI as fallback")
            model_provider_enum = ModelProvider.OPENAI
    else:
        model_provider_enum = model_provider

    # Check cache before making LLM call
    ticker = None
    if state and "data" in state:
        tickers = state["data"].get("tickers", [])
        if tickers:
            ticker = tickers[0]  # Use first ticker as cache key

    if ticker and agent_name:
        try:
            cache = get_llm_cache()
            # Convert prompt to string for hashing
            prompt_str = str(prompt) if not isinstance(prompt, str) else prompt

            # Try to get cached response
            cached_response = cache.get_cached_response(
                ticker=ticker,
                analyst_name=agent_name,
                prompt=prompt_str,
            )

            if cached_response:
                # Reconstruct pydantic model from cached dict
                return pydantic_model(**cached_response)
        except Exception as e:
            # Cache miss or error - proceed with LLM call
            if agent_name:
                progress.update_status(agent_name, ticker, f"Cache miss - calling LLM")

    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider_enum, api_keys)

    # For non-JSON support models, we can use structured output
    if not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    # Call the LLM with retries
    for attempt in range(max_retries):
        try:
            # Call the LLM
            result = llm.invoke(prompt)

            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(result.content)
                if parsed_result:
                    response_model = pydantic_model(**parsed_result)
                else:
                    raise ValueError("Failed to extract JSON from response")
            else:
                response_model = result

            # Store successful response in cache
            if ticker and agent_name:
                try:
                    cache = get_llm_cache()
                    prompt_str = str(prompt) if not isinstance(prompt, str) else prompt
                    cache.store_response(
                        ticker=ticker,
                        analyst_name=agent_name,
                        prompt=prompt_str,
                        response=response_model,
                        model_name=model_name,
                        model_provider=model_provider,
                    )
                except Exception as cache_error:
                    # Log cache storage error but don't fail the request
                    pass

            return response_model

        except Exception as e:
            if agent_name:
                progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation == str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation == float:
            default_values[field_name] = 0.0
        elif field.annotation == int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ == dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from markdown-formatted response."""
    try:
        json_start = content.find("```json")
        if json_start != -1:
            json_text = content[json_start + 7 :]  # Skip past ```json
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                return json.loads(json_text)
    except Exception as e:
        print(f"Error extracting JSON from response: {e}")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")

    if request and hasattr(request, 'get_agent_model_config'):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, 'value') else str(model_provider)

    # Check data.model_config (used by portfolio_manager)
    model_config = state.get("data", {}).get("model_config")
    if model_config:
        model_name = model_config.get("name")
        model_provider = model_config.get("provider")
        if model_name:
            return model_name, model_provider or "OPENAI"

    # Fall back to metadata (used by main.py)
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"

    if hasattr(model_provider, 'value'):
        return model_name, model_provider.value

    return model_name, str(model_provider)
