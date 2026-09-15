"""Automated Job Application runner orchestrating browser navigation, form solving, and resume upload."""

import os
import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from jobflow.core.schema import JobListing, MasterProfile, TailoredResume, ApplicationStatus
from jobflow.automations.browser import BrowserManager
from jobflow.automations.form_solver import FormSolver
from jobflow.config import OUTPUT_DIR

logger = logging.getLogger("jobflow.applier")


class JobApplier:
    def __init__(self, profile: MasterProfile):
        self.profile = profile
        self.solver = FormSolver(profile)

    async def apply_to_job(
        self,
        job: JobListing,
        resume_pdf_path: Path,
        log_callback: Optional[Callable[[str, str], None]] = None
    ) -> Dict[str, Any]:
        """Execute automated or semi-automated application flow for a job listing."""
        def log(message: str, level: str = "info"):
            logger.info(f"[{job.title} @ {job.company}] {message}")
            if log_callback:
                log_callback(message, level)

        if not job.url:
            log("No direct URL provided for this job. Skipping automation.", "error")
            return {"status": ApplicationStatus.FAILED, "error": "Missing job URL"}

        log(f"Starting application pipeline for {job.title} at {job.company}")
        screenshot_dir = OUTPUT_DIR / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / f"app_{job.id or 'temp'}.png"

        try:
            async with BrowserManager() as bm:
                page = await bm.get_page()
                log(f"Navigating to {job.url}...")
                await page.goto(job.url, wait_until="domcontentloaded", timeout=45000)
                await bm.human_delay(2, 4)

                # Look for Easy Apply / Apply buttons
                apply_button_selectors = [
                    "button:has-text('Easy Apply')",
                    "button:has-text('Lamar Cepat')",
                    "button:has-text('Apply Now')",
                    "button:has-text('Lamar Sekarang')",
                    "a:has-text('Apply Now')",
                    "a:has-text('Easy Apply')",
                    "[data-control-name='jobdetails_topcard_inapply']",
                    ".jobs-apply-button",
                ]

                button_found = None
                for selector in apply_button_selectors:
                    try:
                        elem = await page.query_selector(selector)
                        if elem and await elem.is_visible():
                            button_found = elem
                            log(f"Found apply button with selector: {selector}")
                            break
                    except Exception:
                        continue

                if button_found:
                    await button_found.click()
                    await bm.human_delay(2, 3)

                # Form filling loop (up to 5 multi-step pages)
                for step in range(1, 6):
                    log(f"Processing application form step {step}...")

                    # 1. Fill input fields
                    inputs = await page.query_selector_all("input[type='text'], input[type='email'], input[type='tel'], textarea")
                    for inp in inputs:
                        try:
                            if not await inp.is_visible():
                                continue
                            # Get label or aria-label or placeholder
                            name_attr = await inp.get_attribute("name") or ""
                            placeholder = await inp.get_attribute("placeholder") or ""
                            aria_label = await inp.get_attribute("aria-label") or ""
                            identifier = f"{name_attr} {placeholder} {aria_label}".strip()

                            current_val = await inp.input_value()
                            if not current_val and identifier:
                                answer = self.solver.answer_question(identifier)
                                await inp.fill(answer)
                                await bm.human_delay(0.3, 0.7)
                        except Exception:
                            continue

                    # 2. Upload tailored CV if file input is present
                    file_inputs = await page.query_selector_all("input[type='file']")
                    for file_inp in file_inputs:
                        try:
                            if resume_pdf_path.exists():
                                await file_inp.set_input_files(str(resume_pdf_path))
                                log(f"Uploaded tailored resume: {resume_pdf_path.name}")
                                await bm.human_delay(1, 2)
                        except Exception as e:
                            log(f"File upload attempt error: {e}", "warning")

                    # 3. Check for 'Submit' or 'Review' or 'Next' buttons
                    next_selectors = [
                        "button:has-text('Submit application')",
                        "button:has-text('Kirim lamaran')",
                        "button:has-text('Review')",
                        "button:has-text('Tinjau')",
                        "button:has-text('Next')",
                        "button:has-text('Lanjut')",
                        "button[type='submit']",
                        "footer button.artdeco-button--primary"
                    ]

                    clicked_next = False
                    for nxt_sel in next_selectors:
                        try:
                            nxt_btn = await page.query_selector(nxt_sel)
                            if nxt_btn and await nxt_btn.is_visible():
                                btn_text = (await nxt_btn.inner_text()).strip()
                                log(f"Clicking action button: '{btn_text}'")
                                await nxt_btn.click()
                                clicked_next = True
                                await bm.human_delay(2, 3)
                                break
                        except Exception:
                            continue

                    if not clicked_next:
                        log("No further next/submit button found. Form interaction complete.")
                        break

                # Save screenshot of final state
                await page.screenshot(path=str(screenshot_path))
                log(f"Saved application proof screenshot to {screenshot_path.name}")

                return {
                    "status": ApplicationStatus.APPLIED,
                    "screenshot": str(screenshot_path),
                    "message": "Application submitted successfully."
                }

        except Exception as e:
            log(f"Application flow error: {str(e)}", "error")
            return {
                "status": ApplicationStatus.FAILED,
                "error": str(e),
                "screenshot": str(screenshot_path) if screenshot_path.exists() else None
            }
