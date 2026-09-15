"""Base class for Job Extractors."""

from abc import ABC, abstractmethod
from typing import Optional
from jobflow.core.schema import JobListing, PlatformType


class BaseJobExtractor(ABC):
    platform: PlatformType = PlatformType.GENERIC

    @abstractmethod
    async def extract_from_url(self, url: str) -> JobListing:
        """Extract structured job details from a given URL."""
        pass

    @abstractmethod
    def extract_from_raw_text(self, text: str, title: Optional[str] = None, company: Optional[str] = None) -> JobListing:
        """Extract structured job details from raw job posting text."""
        pass
