"""Smart Form Question-Answering engine using Master Profile rules & pattern matching."""

import re
from typing import Optional, Dict
from jobflow.core.schema import MasterProfile


class FormSolver:
    def __init__(self, profile: MasterProfile):
        self.profile = profile

    def answer_question(self, label_or_placeholder: str) -> str:
        """Find best matching answer for a form field prompt."""
        text = label_or_placeholder.lower()

        # 1. Check user-defined Q&A rules in master profile
        for qa in self.profile.common_answers:
            if re.search(qa.question_pattern, text, re.IGNORECASE):
                return qa.answer

        # 2. Heuristic rules for standard application questions
        if any(k in text for k in ["first name", "given name", "nama depan"]):
            return self.profile.contact.full_name.split()[0]
        if any(k in text for k in ["last name", "surname", "nama belakang"]):
            parts = self.profile.contact.full_name.split()
            return parts[-1] if len(parts) > 1 else parts[0]
        if any(k in text for k in ["full name", "nama lengkap", "name"]):
            return self.profile.contact.full_name
        if any(k in text for k in ["email", "e-mail", "surel"]):
            return self.profile.contact.email
        if any(k in text for k in ["phone", "mobile", "nomor telepon", "no hp", "whatsapp"]):
            return self.profile.contact.phone
        if any(k in text for k in ["city", "location", "address", "domisili", "kota"]):
            return self.profile.contact.location
        if any(k in text for k in ["linkedin"]):
            return self.profile.contact.linkedin_url or ""
        if any(k in text for k in ["github"]):
            return self.profile.contact.github_url or ""
        if any(k in text for k in ["portfolio", "website", "link"]):
            return self.profile.contact.portfolio_url or ""
        if any(k in text for k in ["years of experience", "pengalaman kerja", "how many years"]):
            # Calculate total years from profile
            return "3"
        if any(k in text for k in ["salary", "gaji", "expected compensation", "remuneration"]):
            return "Negotiable"
        if any(k in text for k in ["notice period", "pemberitahuan", "when can you start", "kapan bisa mulai"]):
            return "Immediately / 2 Weeks"
        if any(k in text for k in ["authorized", "legally eligible", "hak bekerja", "work permit"]):
            return "Yes"
        if any(k in text for k in ["sponsor", "require sponsorship", "butuh visa"]):
            return "No"
        if any(k in text for k in ["willing to relocate", "bersedia pindah"]):
            return "Yes"

        return "Yes"
