"""Platform-specific Job Extractors for LinkedIn, JobStreet, and Glints."""

import re
import httpx
from bs4 import BeautifulSoup
from typing import Optional
from jobflow.extractors.base import BaseJobExtractor
from jobflow.extractors.generic import GenericJobExtractor
from jobflow.core.schema import JobListing, PlatformType


class LinkedInJobExtractor(BaseJobExtractor):
    platform = PlatformType.LINKEDIN

    async def extract_from_url(self, url: str) -> JobListing:
        # Normalize LinkedIn job URL
        match = re.search(r"currentJobId=(\d+)", url) or re.search(r"view/(\d+)", url)
        job_id = match.group(1) if match else None
        
        target_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}" if job_id else url
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get(target_url, headers=headers)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    title_elem = soup.find("h2", class_=lambda x: x and "top-card-layout__title" in x) or soup.find("h1")
                    company_elem = soup.find("a", class_=lambda x: x and "topcard__org-name-link" in x) or soup.find("span", class_=lambda x: x and "topcard__flavor" in x)
                    desc_elem = soup.find("div", class_=lambda x: x and "show-more-less-html__markup" in x) or soup.find("div", class_=lambda x: x and "description__text" in x)
                    
                    title = title_elem.get_text(strip=True) if title_elem else "LinkedIn Opportunity"
                    company = company_elem.get_text(strip=True) if company_elem else "LinkedIn Employer"
                    description = desc_elem.get_text(separator="\n", strip=True) if desc_elem else resp.text
                    
                    return self.extract_from_raw_text(description, title=title, company=company, url=url)
        except Exception:
            pass

        # Fallback to generic extractor
        generic = GenericJobExtractor()
        listing = await generic.extract_from_url(url)
        listing.platform = PlatformType.LINKEDIN
        return listing

    def extract_from_raw_text(self, text: str, title: Optional[str] = None, company: Optional[str] = None, url: Optional[str] = None) -> JobListing:
        generic = GenericJobExtractor()
        listing = generic.extract_from_raw_text(text, title=title, company=company, url=url)
        listing.platform = PlatformType.LINKEDIN
        return listing


class JobStreetExtractor(BaseJobExtractor):
    platform = PlatformType.JOBSTREET

    async def extract_from_url(self, url: str) -> JobListing:
        generic = GenericJobExtractor()
        listing = await generic.extract_from_url(url)
        listing.platform = PlatformType.JOBSTREET
        return listing

    def extract_from_raw_text(self, text: str, title: Optional[str] = None, company: Optional[str] = None, url: Optional[str] = None) -> JobListing:
        generic = GenericJobExtractor()
        listing = generic.extract_from_raw_text(text, title=title, company=company, url=url)
        listing.platform = PlatformType.JOBSTREET
        return listing


class GlintsExtractor(BaseJobExtractor):
    platform = PlatformType.GLINTS

    async def extract_from_url(self, url: str) -> JobListing:
        generic = GenericJobExtractor()
        listing = await generic.extract_from_url(url)
        listing.platform = PlatformType.GLINTS
        return listing

    def extract_from_raw_text(self, text: str, title: Optional[str] = None, company: Optional[str] = None, url: Optional[str] = None) -> JobListing:
        generic = GenericJobExtractor()
        listing = generic.extract_from_raw_text(text, title=title, company=company, url=url)
        listing.platform = PlatformType.GLINTS
        return listing


def get_job_extractor(url_or_platform: str) -> BaseJobExtractor:
    """Factory to get the right extractor based on URL domain or platform name."""
    s = url_or_platform.lower()
    if "linkedin" in s:
        return LinkedInJobExtractor()
    elif "jobstreet" in s:
        return JobStreetExtractor()
    elif "glints" in s:
        return GlintsExtractor()
    return GenericJobExtractor()
