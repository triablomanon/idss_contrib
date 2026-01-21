"""
Interview workflow - asks questions to understand user needs before making recommendations.

This workflow runs until the interview is complete (threshold reached or user requests products).
"""
import os
from typing import Any, Dict, Optional, Callable
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from idss_agent.utils.logger import get_logger
from idss_agent.utils.config import get_config
from idss_agent.utils.prompts import render_prompt
from idss_agent.state.schema import (
    ProductSearchState,
    get_latest_user_message,
    ProductFiltersPydantic,
    ImplicitPreferencesPydantic,
    AgentResponse
)
from idss_agent.processing.semantic_parser import semantic_parser_node
from idss_agent.processing.recommendation import update_recommendation_list
from idss_agent.agents.discovery import discovery_agent

logger = get_logger("workflows.interview")


# This defines the "Must Have" fields for each component type.
REQUIRED_SPECS_MAP = {
    "gpu": ["price", "target_resolution", "recommended_psu"],
    "graphics card": ["price", "target_resolution", "recommended_psu"],
    "cpu": ["price", "primary_use_case", "socket"],
    "processor": ["price", "primary_use_case", "socket"],
    "motherboard": ["socket", "form_factor", "wifi"],
    "monitor": ["target_resolution", "screen_size", "price"],
    # Fallback for unknown or full builds
    "default": ["part_type", "price", "primary_use_case"]
}

def get_missing_requirements(filters: Dict[str, Any]) -> list[str]:
    """
    Compare current filters against strict requirements to find what's missing.
    """
    # 1. Determine the category (default to "default" if unknown)
    part_type = filters.get("part_type", "").lower()
    
    # Handle broad categories or synonyms if needed
    if not part_type:
        required_fields = REQUIRED_SPECS_MAP["default"]
    else:
        # Fuzzy match or direct lookup
        required_fields = REQUIRED_SPECS_MAP.get(part_type, REQUIRED_SPECS_MAP["default"])

    # 2. Check what is missing
    missing = []
    for field in required_fields:
        # specialized check for price since it maps to price_min/max/range
        if field == "price":
            if not (filters.get("price") or filters.get("price_max")):
                missing.append("Budget / Price Range")
        elif field not in filters or not filters[field]:
            # Convert snake_case to Human Readable
            human_readable = field.replace("_", " ").title()
            missing.append(human_readable)
            
    return missing

def format_known_info(filters: Dict[str, Any]) -> str:
    """Format known filters for the prompt to prevent redundancy."""
    if not filters:
        return "Nothing explicitly known yet."
    
    lines = []
    for k, v in filters.items():
        if v:
            lines.append(f"- {k.replace('_', ' ').title()}: {v}")
    return "\n".join(lines)



# Structured output schema for interview mode
class InterviewResponse(BaseModel):
    """Structured response from interview agent with should_end flag."""
    ai_response: str = Field(
        description="Your conversational response to the user (2-3 sentences max)",
        max_length=500
    )
    quick_replies: Optional[list[str]] = Field(
        default=None,
        description=(
            "Short answer options (2-5 words each) for questions in your response. "
            "Provide 2-4 options if you ask a direct question. "
        ),
        max_length=4
    )
    should_end: bool = Field(description="True if interview mode should end, false to continue")


# Structured output schema for extraction
class ExtractionResult(BaseModel):
    """Structured extraction from interview conversation."""
    explicit_filters: ProductFiltersPydantic = Field(
        default_factory=ProductFiltersPydantic,
        description="Explicit product filters with specific fields"
    )
    implicit_preferences: ImplicitPreferencesPydantic = Field(
        default_factory=ImplicitPreferencesPydantic,
        description="Implicit preferences with specific fields"
    )
    questions_asked: list[str] = Field(
        default_factory=list,
        description=(
            "Topics covered during the interview conversation. "
            "Include topics that were asked about OR volunteered by the user. "
            "Possible topics: budget, usage, priorities, product_type, features, "
            "compatibility, timeline, brand_preference, etc."
        )
    )


def should_end_interview(state: ProductSearchState) -> bool:
    """
    Check if interview should end based on LLM's decision or max turns.

    Returns True if:
    - LLM set should_end=True in last response OR
    - Hit max conversation exchanges (safety limit)
    """
    # Check if LLM decided to end
    if state.get("_interview_should_end", False):
        return True

    # Safety limit - max turns from config
    config = get_config()
    max_questions = config.limits.get('max_interview_questions', 8)
    conversation = state.get("conversation_history", [])
    turn_count = len([msg for msg in conversation if msg.__class__.__name__ == 'HumanMessage'])

    if turn_count >= max_questions:
        logger.info(f"Hit max turns ({max_questions}), ending interview")
        return True

    return False


def interview_node(state: ProductSearchState) -> ProductSearchState:
    """
    Interview node that asks questions like a salesperson.

    Uses structured output with conversation history as user input for optimal prompt caching.

    Args:
        state: Current state

    Returns:
        Updated state with AI response and should_end flag
    """
    # Get progress callback from state if available
    progress_callback = state.get("_progress_callback")

    # Emit progress: Starting interview
    if progress_callback:
        progress_callback({
            "step_id": "interview_questions",
            "description": "Conducting interview",
            "status": "in_progress"
        })

    user_input = get_latest_user_message(state)

    # Gap Analysis Logic 
    current_filters = state.get("explicit_filters", {})
    
    # 1. Calculate Gaps
    missing_info_list = get_missing_requirements(current_filters)
    known_info_str = format_known_info(current_filters)
    missing_info_str = ", ".join(missing_info_list) if missing_info_list else "None - ready to recommend"

    # 2. Smart Greeting / First Turn Logic
    # If it's the first turn BUT we already extracted a part type (e.g. "I want a GPU"),
    # we skip the generic greeting and go straight to specific questions.
    is_first_turn = not user_input
    has_specific_intent = "part_type" in current_filters
    
    if is_first_turn and not has_specific_intent:
        # True Cold Start: We know nothing.
        state["ai_response"] = "Hi! I can help you find PC parts. Are you building a new PC from scratch, or upgrading a specific component?"
        state["quick_replies"] = ["Building New PC", "Upgrading Component", "Just Browsing"]
        state["_interview_should_end"] = False
        if progress_callback:
            progress_callback({"step_id": "interview_questions", "status": "completed"})
        return state

    # Get configuration
    config = get_config()
    model_config = config.get_model_config('interview')
    max_history = config.limits.get('max_conversation_history', 10)

    # Create LLM with config parameters
    llm = ChatOpenAI(
        model=model_config['name'],
        temperature=model_config['temperature'],
        max_tokens=model_config.get('max_tokens', 1000)
    )
    structured_llm = llm.with_structured_output(InterviewResponse)

    system_prompt = render_prompt(
        'interview_system.j2',
        extra_context={
            'known_info_summary': known_info_str,
            'missing_critical_info': missing_info_str
        }
    )
    
    messages = [SystemMessage(content=system_prompt)]
    
    # Add history
    conversation_history = state["conversation_history"]
    if len(conversation_history) > max_history:
        conversation_history = conversation_history[-max_history:]
    messages.extend(conversation_history)

    # 4. Invoke
    response: InterviewResponse = structured_llm.invoke(messages)

    # 5. Logic Check: If no missing info, force end (unless LLM disagrees strongly)
    if not missing_info_list and len(conversation_history) > 2:
        logger.info("Gap analysis shows all critical info gathered. Encouraging end of interview.")

    state["_interview_should_end"] = response.should_end
    state["ai_response"] = response.ai_response
    state["quick_replies"] = response.quick_replies if config.features.get('enable_quick_replies', True) else None
    
    if progress_callback:
        progress_callback({"step_id": "interview_questions", "status": "completed"})

    return state



def make_initial_recommendation(state: ProductSearchState) -> ProductSearchState:
    """
    Called once at the end of interview to:
    1. Parse entire interview conversation for filters/preferences using structured output
    2. Search for actual available products using electronics API
    3. Use discovery agent to present products conversationally
    4. Mark interview as complete

    Args:
        state: Current state

    Returns:
        Updated state with interviewed=True and initial recommendations
    """
    logger.info("Interview complete! Extracting preferences and searching for available products...")

    # Get progress callback from state if available
    progress_callback = state.get("_progress_callback")

    # Emit progress: Starting extraction
    if progress_callback:
        progress_callback({
            "step_id": "extracting_preferences",
            "description": "Extracting your preferences",
            "status": "in_progress"
        })

    # Step 1: Extract filters/preferences using structured output
    # Get entire interview conversation
    interview_conversation = "\n".join([
        f"{'Customer' if msg.__class__.__name__ == 'HumanMessage' else 'Salesperson'}: {msg.content}"
        for msg in state.get("conversation_history", [])
    ])

    # Get configuration
    config = get_config()
    model_config = config.get_model_config('interview_extraction')

    # Create LLM with config parameters
    llm = ChatOpenAI(
        model=model_config['name'],
        temperature=model_config['temperature'],
        max_tokens=model_config.get('max_tokens', 2000)
    )
    structured_llm = llm.with_structured_output(ExtractionResult)

    # Load extraction prompt from template
    extraction_system_prompt = render_prompt('interview_extraction.j2')

    extraction_prompt = f"""
CONVERSATION:
{interview_conversation}
"""
    messages = [
        SystemMessage(content=extraction_system_prompt),
        HumanMessage(content=extraction_prompt)
    ]

    result: ExtractionResult = structured_llm.invoke(messages)

    state["explicit_filters"] = {**state["explicit_filters"], **result.explicit_filters.model_dump(exclude_none=True)}
    state["implicit_preferences"] = {**state["implicit_preferences"], **result.implicit_preferences.model_dump(exclude_none=True)}
    state["questions_asked"] = result.questions_asked  # Track topics covered during interview for discovery handoff

    logger.info(f"Extracted filters: {state['explicit_filters']}")
    logger.info(f"Extracted preferences: {state['implicit_preferences']}")
    logger.info(f"Topics covered in interview: {state['questions_asked']}")

    # Emit progress: Extraction complete
    if progress_callback:
        progress_callback({
            "step_id": "extracting_preferences",
            "description": "Preferences extracted",
            "status": "completed"
        })

    # Step 2: Search for actual available products using electronics API
    state = update_recommendation_list(state, progress_callback)

    # Step 3: Use discovery agent to present products conversationally
    state = discovery_agent(state, progress_callback)

    # Step 4: Mark interview complete
    state["interviewed"] = True

    # Clean up temporary flag
    if "_interview_should_end" in state:
        del state["_interview_should_end"]

    return state


def decide_next_step(state: ProductSearchState) -> str:
    """Router to decide if interview should continue or make recommendations."""
    if should_end_interview(state):
        return "make_recommendation"
    return END


# Create wrapper for semantic_parser_node that extracts callback from state
def semantic_parser_wrapper(state: ProductSearchState) -> ProductSearchState:
    """
    Wrapper to pass progress_callback from state to semantic_parser_node.

    Optimization: Skip parsing if already done by supervisor to avoid duplicate LLM calls.
    """
    # Check if semantic parsing was already done by supervisor
    if state.get("_semantic_parsing_done", False):
        logger.info("Skipping duplicate semantic parsing (already done by supervisor)")
        # Clear the flag so next turn will parse normally
        state['_semantic_parsing_done'] = False
        return state

    # Otherwise, do semantic parsing
    progress_callback = state.get("_progress_callback")
    return semantic_parser_node(state, progress_callback)


# Create LangGraph StateGraph for interview workflow
def create_interview_graph():
    """Create the interview workflow graph."""
    workflow = StateGraph(ProductSearchState)

    # Add nodes (using wrapper for semantic_parser to pass callback)
    workflow.add_node("semantic_parser", semantic_parser_wrapper)
    workflow.add_node("interview", interview_node)
    workflow.add_node("make_recommendation", make_initial_recommendation)

    # Add edges
    workflow.set_entry_point("semantic_parser")
    workflow.add_edge("semantic_parser", "interview")
    workflow.add_conditional_edges(
        "interview",
        decide_next_step,
        {
            "make_recommendation": "make_recommendation",
            END: END
        }
    )
    workflow.add_edge("make_recommendation", END)

    return workflow.compile()


# Create the compiled graph (singleton)
_interview_graph = None

def get_interview_graph():
    """Get or create the interview workflow graph."""
    global _interview_graph
    if _interview_graph is None:
        _interview_graph = create_interview_graph()
    return _interview_graph


def run_interview_workflow(
    user_input: str,
    state: ProductSearchState,
    progress_callback: Optional[Callable[[dict], None]] = None
) -> ProductSearchState:
    """
    Main interview workflow entry point.

    Args:
        user_input: User's message
        state: Current state
        progress_callback: Optional callback for progress updates

    Returns:
        Updated state
    """
    # Store progress callback in state for nodes to access
    # (LangGraph nodes only receive state parameter)
    if progress_callback:
        state["_progress_callback"] = progress_callback

    graph = get_interview_graph()
    result = graph.invoke(state)

    # Clean up progress callback from state
    if "_progress_callback" in result:
        del result["_progress_callback"]

    return result
