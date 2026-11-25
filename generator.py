import os
import google.generativeai as genai


def load_system_prompt(prompt_file="system_prompt.txt"):
    """Loads the system prompt for personalized line generation from disk."""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as f:
            return f.read()
    print(f"Warning: System prompt file '{prompt_file}' not found. Proceeding without system instruction.")
    return ""


class LineGenerator:
    """Generates grounded, 1-sentence B2B outreach lines using Google Gemini."""

    def __init__(
        self,
        primary_api_key,
        backup_api_key="",
        model_name="models/gemini-3.7-flash",
        prompt_file="system_prompt.txt",
    ):
        self.model_name = model_name
        self.active_key = None
        self.model = None
        self._init_client(primary_api_key, backup_api_key, prompt_file)

    def _init_client(self, primary_api_key, backup_api_key, prompt_file):
        keys_to_try = [k.strip() for k in (primary_api_key, backup_api_key) if k and k.strip()]
        if not keys_to_try:
            raise RuntimeError(
                "Missing GEMINI_API_KEY. Set it in your environment or a .env file (see .env.example)."
            )

        last_error = None
        for idx, key in enumerate(keys_to_try):
            try:
                genai.configure(api_key=key)
                test_model = genai.GenerativeModel(self.model_name)
                test_model.generate_content("ping")
                self.active_key = key
                break
            except Exception as e:
                last_error = e
                if idx == 0 and len(keys_to_try) > 1:
                    print("Primary Gemini API key check failed; attempting backup key...")
        else:
            raise RuntimeError(f"Failed to initialize Gemini client: {last_error}")

        system_prompt = load_system_prompt(prompt_file)
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
        )

    def generate(self, company_name, company_info):
        """Returns a single personalized outreach sentence grounded in website research."""
        user_content = (
            f"Target Company: {company_name}\n\n"
            f"Entire Website Research:\n{company_info}"
        )

        try:
            response = self.model.generate_content(user_content)
            text = response.text.strip().replace('"', "")
            if "—" in text:
                text = text.split("—")[0].strip()
                if not text.endswith("."):
                    text += "."
            return text
        except Exception as e:
            print(f"Error generating line for {company_name}: {e}")
            return "Could not generate line."
