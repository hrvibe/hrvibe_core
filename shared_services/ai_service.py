from openai import OpenAI
import json
import logging
import os
import sys
import time
from typing import List, Dict
from pathlib import Path

from database import Vacancies
from shared_services.db_service import get_column_value_in_db

# Add project root to path to access shared_services
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared_services.constants import MODEL_NAME

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



def analyze_vacancy_with_ai(vacancy_data: json, prompt_vacancy_analysis_text: str, model: str = MODEL_NAME) -> dict:
    """
    Sends vacancy description JSON + prompt to OpenAI and returns structured JSON with analysis.
    Args:
        vacancy_data (dict): Vacancy description as a dictionary.
        prompt_text (str): Instruction for the model.
        model (str): Model name (default "gpt-4o").
    Returns:
        dict: Parsed JSON response from the model.
    """
    
    logger.debug("Preparing AI request for vacancy analysis…")
    
    '''
    user_message = f"""
    Вакансия:
    {json.dumps(vacancy_data, ensure_ascii=False, indent=2)}
    Задача анализа:
    {prompt_vacancy_analysis_text}
    """
    logger.debug(f"Sending request to OpenAI model='{model}'. Waiting for response…")
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты — профессиональный сорсер резюме."},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"}  # ensures valid JSON output
        )
        logger.debug("Response received from OpenAI. Parsing…")
    except Exception as e:
        logger.error(f"OpenAI request failed: {e}", exc_info=True)
        return {"error": str(e)}
    try:
        result = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        logger.warning("Response is not valid JSON, returning raw text instead.")
        result = {"raw_output": response.choices[0].message.content}
    logger.debug("Vacancy analysis completed.")
    return result
    '''

    # !!! FOR TESTING ONLY !!!
    # !!! FOR TESTING ONLY !!!
    # !!! FOR TESTING ONLY !!!
    # !!! FOR TESTING ONLY !!!

    with open("/Users/gridavyv/HRVibe/hrvibe_2.1/test_data/fake_sourcing_criterias.json", "r", encoding="utf-8") as f:
        result = json.load(f)
    logger.debug(f"Sourcing criterias fetched from fake file: {result}")
    return result

    # !!! FOR TESTING ONLY !!!
    # !!! FOR TESTING ONLY !!!
    # !!! FOR TESTING ONLY !!!  


def format_sourcing_criterias_analysis_result_for_markdown(vacancy_id: str) -> str:
    """Load sourcing criteria JSON and format requirements for Markdown output.

    Input path to JSON file with structure example:
    {
      "requirements": {
        "must": ["...", "..."],
        "nice_to_have": ["...", "..."]
      }
    }

    Output format:
    must
    - item1
    - item2

    nice_to_have
    - item1
    - item2
    """
    try:

        data = get_column_value_in_db(db_model=Vacancies, record_id=vacancy_id, field_name="sourcing_criterias_json")

    except Exception as e:
        return f"[ERROR] Failed to read sourcing_criterias_json for {vacancy_id}: {e}"

    requirements = {}
    if isinstance(data, dict):
        requirements = data.get("requirements", {}) or {}

    must_list = []
    nice_list = []
    if isinstance(requirements, dict):
        must_list = requirements.get("must", []) or []
        nice_list = requirements.get("nice_to_have", []) or []

    lines = []
    lines.append("*Обязательно*")
    for item in must_list:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("*Желательно*:")
    for item in nice_list:
        lines.append(f"- {item}")
    return "\n".join(lines)


def analyze_resume_with_ai(vacancy_description: json, sourcing_criterias: json, resume_data: json, prompt_resume_analysis_text: str, model: str = MODEL_NAME) -> dict:
    """
    Sends vacancy description JSON + prompt to OpenAI and returns structured JSON with analysis.
    Args:
        vacancy_data (dict): Vacancy description as a dictionary.
        prompt_text (str): Instruction for the model.
        model (str): Model name (default "gpt-4o").
    Returns:
        dict: Parsed JSON response from the model.
    """
    user_message = f"""
    Вакансия:
    {json.dumps(vacancy_description, ensure_ascii=False, indent=2)}
    Критерии отбора:
    {json.dumps(sourcing_criterias, ensure_ascii=False, indent=2)}
    Резюме кандидата:
    {json.dumps(resume_data, ensure_ascii=False, indent=2)}
    Задача анализа:
    {prompt_resume_analysis_text}
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "Ты — профессиональный сорсер резюме."},
            {"role": "user", "content": user_message}
        ],
        response_format={"type": "json_object"}  # ensures valid JSON output
    )
    try:
        result = json.loads(response.choices[0].message.content)
    except json.JSONDecodeError:
        logger.warning("Response is not valid JSON, returning raw text instead.")
        result = {"raw_output": response.choices[0].message.content}
    return result

# ----- OPENAI ASSISTANT functions -----
"""
def wait_for_run_completion(thread_id: str, run_id: str, timeout_s: int = 120, poll_s: float = 1.2):
    #Poll run status until completed/failed/expired or timeout.
    start = time.time()
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        status = run.status
        if status in ("completed", "failed", "expired", "cancelled"):
            return status
        if time.time() - start > timeout_s:
            return "timeout"
        time.sleep(poll_s)


def extract_last_assistant_json(thread_id: str) -> Dict:
    #Get the latest assistant message from the thread and parse JSON.
    msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=10)
    for m in msgs.data:
        if m.role == "assistant":
            # Assistant content may be a list of text parts
            for part in m.content:
                if part.type == "text":
                    txt = part.text.value.strip()
                    # Try to locate JSON in the text (expecting pure JSON)
                    try:
                        return json.loads(txt)
                    except Exception:
                        # Attempt to recover if model wrapped JSON in backticks
                        if "```" in txt:
                            try:
                                fenced = txt.split("```")[1]
                                return json.loads(fenced)
                            except Exception:
                                pass
            break
    raise ValueError("No assistant JSON found in thread messages.")


def create_assistant() -> str:
    assistant = client.beta.assistants.create(
        name="Resume Sourcer",
        instructions=SYSTEM_INSTRUCTIONS,
        model=MODEL,
        tools=[]  # add tools if needed later
    )
    return assistant.id


def process_resumes(
    resumes: List[Dict],
    assistant_id: str,
    delete_thread_after: bool = True
) -> List[Dict]:
    '''
    For each resume:
      - add a user message with resume JSON
      - run the assistant
      - collect strict JSON result
    Returns list of JSON results (one per resume).
    '''
    thread = client.beta.threads.create()
    thread_id = thread.id
    results = []

    try:
        for idx, resume in enumerate(resumes, start=1):
            user_msg = {
                "role": "user",
                "content": f"Резюме #{idx}:\n\n```json\n{json.dumps(resume, ensure_ascii=False)}\n```\n"
                           f"Оцени это резюме по заданным criteria и верни СТРОГО JSON по схеме."
            }
            client.beta.threads.messages.create(thread_id=thread_id, **user_msg)

            run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=assistant_id)
            status = wait_for_run_completion(thread_id, run.id)

            if status != "completed":
                results.append({
                    "error": f"Run status: {status}",
                    "resume_index": idx
                })
                continue

            out_json = extract_last_assistant_json(thread_id)
            results.append(out_json)

        return results

    finally:
        if delete_thread_after:
            try:
                client.beta.threads.delete(thread_id=thread_id)
            except Exception:
                pass


if __name__ == "__main__":
    # === Example usage ===
    # 1) Prepare your resume list (dicts). Load from files or API.
    resumes_batch = [
        # json.loads(open("resume_1.json","r",encoding="utf-8").read()),
        # json.loads(open("resume_2.json","r",encoding="utf-8").read()),
        # ...
    ]

    if not resumes_batch:
        logger.warning("No resumes provided. Fill `resumes_batch` list with resume dicts.")
        exit(0)

    # 2) Create assistant (or reuse existing one by ID)
    assistant_id = create_assistant()

    # 3) Run evaluation for all resumes in one stateful thread
    results = process_resumes(resumes_batch, assistant_id=assistant_id, delete_thread_after=True)

"""