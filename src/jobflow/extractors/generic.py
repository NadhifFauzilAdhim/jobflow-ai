"""Generic Job Extractor using HTTP fetch, BeautifulSoup, and text parsing."""

import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional, List
from jobflow.extractors.base import BaseJobExtractor
from jobflow.core.schema import JobListing, PlatformType


class GenericJobExtractor(BaseJobExtractor):
    platform = PlatformType.GENERIC

    async def extract_from_url(self, url: str) -> JobListing:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
        }
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style tags
        for s in soup(["script", "style", "nav", "footer", "header"]):
            s.decompose()

        page_title = soup.title.string.strip() if soup.title and soup.title.string else "Job Opening"
        
        # Heuristic title / company extraction from page title (e.g. "Software Engineer at Google" or "Google hiring Software Engineer")
        title = page_title
        company = "Unknown Company"
        if " at " in page_title:
            parts = page_title.split(" at ")
            title = parts[0].strip()
            company = parts[1].split("|")[0].split("-")[0].strip()
        elif " - " in page_title:
            parts = page_title.split(" - ")
            title = parts[0].strip()
            company = parts[1].strip()

        # Extract main text
        main_content = ""
        main_tag = soup.find("main") or soup.find("article") or soup.find("body")
        if main_tag:
            main_content = main_tag.get_text(separator="\n", strip=True)

        return self.extract_from_raw_text(main_content, title=title, company=company, url=url)

    def extract_from_raw_text(
        self,
        text: str,
        title: Optional[str] = None,
        company: Optional[str] = None,
        url: Optional[str] = None
    ) -> JobListing:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)

        final_title = title or (lines[0] if lines else "Software Engineer")
        final_company = company or (lines[1] if len(lines) > 1 else "Tech Company")

        # Heuristic requirements extraction
        requirements: List[str] = []
        is_req_section = False
        req_triggers = ["requirements", "qualifications", "what you need", "kualifikasi", "persyaratan", "skills"]
        
        for line in lines:
            line_lower = line.lower()
            if any(t in line_lower for t in req_triggers) and len(line) < 40:
                is_req_section = True
                continue
            elif is_req_section and any(t in line_lower for t in ["benefits", "about us", "tentang kami", "responsibilities", "tanggung jawab"]):
                is_req_section = False

            if is_req_section:
                if line.startswith(("-", "•", "*", "1.", "2.", "3.", "4.", "5.")):
                    requirements.append(re.sub(r"^[-•*\d.]+\s*", "", line).strip())
                elif len(line) > 10 and len(requirements) < 15:
                    requirements.append(line)

        return JobListing(
            title=final_title,
            company=final_company,
            url=url,
            platform=self.platform,
            description=cleaned_text,
            requirements=requirements[:15]
        )
