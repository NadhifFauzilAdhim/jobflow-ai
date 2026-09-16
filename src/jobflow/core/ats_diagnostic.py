"""ATS Resume Diagnostic & Deficiency Detection Engine.

Analyzes resumes across the exact categories checked by modern ATS systems
(e.g., Resume Worded, Jobscan):
- ATS Parse Rate & Format
- Quantifying Impact (Metrics, Numbers, Google X-Y-Z formula)
- Repetition & Action Verb Variety
- Spelling, Grammar & Clean Formatting
- Bullets Consistency & Length
- Core Job Keywords & Section Completeness
"""

import re
from typing import List, Dict, Any, Optional, Set, Tuple
from jobflow.core.schema import (
    TailoredResume,
    JobListing,
    ATSDiagnosticReport,
    ATSCategoryStatus,
    ATSDiagnosticIssue,
)
from jobflow.core.ats_scorer import extract_keywords, clean_and_tokenize


POWER_VERB_ALTERNATIVES: Dict[str, List[str]] = {
    "built": ["Architected", "Engineered", "Constructed", "Formulated", "Deployed"],
    "developed": ["Engineered", "Designed", "Authored", "Programmed", "Implemented"],
    "managed": ["Orchestrated", "Spearheaded", "Directed", "Guided", "Administered"],
    "created": ["Pioneered", "Devised", "Established", "Launched", "Originated"],
    "led": ["Spearheaded", "Mobilized", "Directed", "Championed", "Guided"],
    "worked": ["Collaborated", "Contributed", "Partnered", "Executed", "Engaged"],
    "responsible": ["Accountable for", "Tasked with delivering", "Oversaw", "Executed"],
    "assisted": ["Facilitated", "Accelerated", "Supported", "Bolstered"],
    "helped": ["Facilitated", "Empowered", "Advanced", "Enabled"],
    "membangun": ["Merancang", "Mengarsiteki", "Mengembangkan", "Mengimplementasikan"],
    "membuat": ["Menciptakan", "Merintis", "Merancang", "Mengembangkan"],
    "mengelola": ["Memimpin", "Mengorkestrasi", "Mengarahkan", "Mengkoordinasi"],
    "memimpin": ["Mempelopori", "Mengarahkan", "Mengawal", "Mengkoordinasikan"],
}

METRIC_PATTERNS = [
    re.compile(r'\b\d+[\d,\.]*\b'),              # Digits (e.g., 100, 1,000, 3.89)
    re.compile(r'\d+\s*%'),                       # Percentages (e.g. 40%, 99.9%)
    re.compile(r'\b\d+\s*(?:k|m|b|ms|s|fps|x|gb|tb|rps|qps)\b', re.IGNORECASE), # Scale
    re.compile(r'(?:\$|rp|€|£)\s*[\d,\.]+', re.IGNORECASE), # Currency
    re.compile(r'\b(?:reduced|cut|increased|improved|scaled|boosted|grew|accelerated|doubled|tripled)\b', re.IGNORECASE) # Verbs indicating metric impact
]


class ATSResumeDiagnostic:
    """Diagnostic scanner identifying deficiencies in resumes with actionable feedback and context questions."""

    def __init__(self):
        pass

    def analyze_resume(
        self,
        resume: TailoredResume,
        job: Optional[JobListing] = None
    ) -> ATSDiagnosticReport:
        """Run a full ATS diagnostic audit on the provided tailored resume."""
        issues: List[ATSDiagnosticIssue] = []
        context_required_issues: List[ATSDiagnosticIssue] = []

        # 1. Inspect Quantifying Impact
        qi_issues, qi_score = self._check_quantifying_impact(resume)
        issues.extend(qi_issues)
        for iss in qi_issues:
            if iss.needs_user_context:
                context_required_issues.append(iss)

        # 2. Inspect Repetition & Action Verb Variety
        rep_issues, rep_score = self._check_repetition(resume)
        issues.extend(rep_issues)

        # 3. Inspect Spelling & Grammar / Formatting Quality
        sg_issues, sg_score = self._check_spelling_and_grammar(resume)
        issues.extend(sg_issues)

        # 4. Inspect Bullets Consistency & Length
        bc_issues, bc_score = self._check_bullets_consistency(resume)
        issues.extend(bc_issues)

        # 5. Inspect ATS Parse Rate & Essential Sections
        pr_issues, pr_score = self._check_parse_rate(resume)
        issues.extend(pr_issues)

        sec_issues, sec_score = self._check_sections(resume)
        issues.extend(sec_issues)

        # 6. Inspect Keywords if job listing is provided
        kw_score = 100.0
        if job:
            kw_issues, kw_score = self._check_keywords(resume, job)
            issues.extend(kw_issues)

        # Content score is weighted average of Content components
        content_score = round(
            (qi_score * 0.35) +
            (rep_score * 0.20) +
            (sg_score * 0.25) +
            (bc_score * 0.20),
            1
        )

        overall_score = round(
            (content_score * 0.45) +
            (sec_score * 0.25) +
            (pr_score * 0.15) +
            (kw_score * 0.15),
            1
        )

        # Build categories breakdown matching ATS checker UI
        categories = [
            ATSCategoryStatus(
                category_id="parse_rate",
                name="ATS Parse Rate",
                score=pr_score,
                status="pass" if not pr_issues else "warning",
                status_label="No issues" if not pr_issues else f"{len(pr_issues)} issue{'s' if len(pr_issues) > 1 else ''}",
                issue_count=len(pr_issues),
                issues=pr_issues
            ),
            ATSCategoryStatus(
                category_id="quantifying_impact",
                name="Quantifying Impact",
                score=qi_score,
                status="pass" if not qi_issues else ("error" if len(qi_issues) > 2 else "warning"),
                status_label="No issues" if not qi_issues else f"{len(qi_issues)} issue{'s' if len(qi_issues) > 1 else ''}",
                issue_count=len(qi_issues),
                issues=qi_issues
            ),
            ATSCategoryStatus(
                category_id="repetition",
                name="Repetition & Action Verbs",
                score=rep_score,
                status="pass" if not rep_issues else "warning",
                status_label="No issues" if not rep_issues else f"{len(rep_issues)} issue{'s' if len(rep_issues) > 1 else ''}",
                issue_count=len(rep_issues),
                issues=rep_issues
            ),
            ATSCategoryStatus(
                category_id="spelling_grammar",
                name="Spelling & Formatting Quality",
                score=sg_score,
                status="pass" if not sg_issues else ("error" if len(sg_issues) > 3 else "warning"),
                status_label="No issues" if not sg_issues else f"{len(sg_issues)} issue{'s' if len(sg_issues) > 1 else ''}",
                issue_count=len(sg_issues),
                issues=sg_issues
            ),
            ATSCategoryStatus(
                category_id="bullets_consistency",
                name="Bullets Consistency & Length",
                score=bc_score,
                status="pass" if not bc_issues else "warning",
                status_label="No issues" if not bc_issues else f"{len(bc_issues)} issue{'s' if len(bc_issues) > 1 else ''}",
                issue_count=len(bc_issues),
                issues=bc_issues
            ),
            ATSCategoryStatus(
                category_id="sections",
                name="Sections Completeness",
                score=sec_score,
                status="pass" if not sec_issues else "warning",
                status_label="No issues" if not sec_issues else f"{len(sec_issues)} issue{'s' if len(sec_issues) > 1 else ''}",
                issue_count=len(sec_issues),
                issues=sec_issues
            )
        ]

        # Summary insight
        if len(issues) == 0:
            insight = "Sempurna! Dokumen CV Anda memenuhi seluruh standar ATS dan Google X-Y-Z formula dengan skor optimal."
        else:
            top_cat = "pencapaian terukur" if qi_issues else ("pengulangan kata kerja" if rep_issues else "kualitas penulisan")
            insight = (
                f"Ditemukan {len(issues)} potensi perbaikan (terutama pada {top_cat}). "
                f"Terdapat {len(context_required_issues)} poin yang membutuhkan angka/konteks tambahan dari Anda untuk memaksimalkan skor konten ATS."
            )

        return ATSDiagnosticReport(
            overall_score=overall_score,
            content_score=content_score,
            sections_score=sec_score,
            keywords_score=kw_score,
            parse_rate_score=pr_score,
            categories=categories,
            issues=issues,
            context_required_issues=context_required_issues,
            summary_insight=insight
        )

    def _has_metric(self, text: str) -> bool:
        """Check if a bullet text contains quantifiable metrics, percentages, or numbers."""
        for pattern in METRIC_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _check_quantifying_impact(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Verify that experience, projects, and custom section bullets have quantifiable metrics."""
        issues: List[ATSDiagnosticIssue] = []
        total_bullets = 0
        quantified_bullets = 0

        # Check Experience
        for exp_idx, exp in enumerate(resume.experience):
            for b_idx, bullet in enumerate(exp.highlights):
                total_bullets += 1
                if self._has_metric(bullet):
                    quantified_bullets += 1
                else:
                    field_id = f"ctx_exp_{exp_idx}_bullet_{b_idx}"
                    issues.append(ATSDiagnosticIssue(
                        id=f"qi_exp_{exp_idx}_{b_idx}",
                        category="quantifying_impact",
                        severity="warning",
                        title="Poin Pengalaman Belum Memiliki Metrik Terukur",
                        description=(
                            f"Poin ini menjelaskan tugas di {exp.company}, namun belum memiliki bukti angka/metrik terukur. "
                            "Standar ATS dan recruiter mengharapkan formula Google X-Y-Z (Accomplished [X] as measured by [Y], by doing [Z])."
                        ),
                        section_name=f"Experience — {exp.position} @ {exp.company}",
                        target_text=bullet,
                        suggestion="Tambahkan persentase peningkatan efisiensi, volume data/transaksi, jumlah pengguna, atau penghematan waktu.",
                        needs_user_context=True,
                        context_question=(
                            f"Pada posisi '{exp.position}' di '{exp.company}': "
                            f"Berapa estimasi metrik hasil (misal: persentase efisiensi, volume transaksi, atau ukuran tim) untuk poin: \"{bullet[:80]}...\"?"
                        ),
                        context_field_id=field_id
                    ))

        # Check Featured Projects
        for p_idx, proj in enumerate(resume.projects):
            for b_idx, bullet in enumerate(proj.highlights):
                total_bullets += 1
                if self._has_metric(bullet):
                    quantified_bullets += 1
                else:
                    field_id = f"ctx_proj_{p_idx}_bullet_{b_idx}"
                    issues.append(ATSDiagnosticIssue(
                        id=f"qi_proj_{p_idx}_{b_idx}",
                        category="quantifying_impact",
                        severity="warning",
                        title="Poin Proyek Belum Memiliki Metrik Terukur",
                        description=(
                            f"Poin pada proyek '{proj.name}' belum memiliki angka konkret yang membuktikan skala atau dampaknya."
                        ),
                        section_name=f"Featured Projects — {proj.name}",
                        target_text=bullet,
                        suggestion="Sertakan angka seperti throughput transaksi, akurasi model, penurunan latensi, atau jumlah pengguna aktif.",
                        needs_user_context=True,
                        context_question=(
                            f"Pada proyek '{proj.name}': "
                            f"Berapa estimasi metrik performa atau skala (misal: akurasi %, rps transaksi, atau efisiensi p95) untuk: \"{bullet[:80]}...\"?"
                        ),
                        context_field_id=field_id
                    ))

        # Check Custom Sections
        for cs_idx, cs in enumerate(resume.custom_sections):
            for item_idx, item in enumerate(cs.items):
                for b_idx, bullet in enumerate(item.bullets):
                    total_bullets += 1
                    if self._has_metric(bullet):
                        quantified_bullets += 1
                    else:
                        field_id = f"ctx_custom_{cs_idx}_{item_idx}_{b_idx}"
                        issues.append(ATSDiagnosticIssue(
                            id=f"qi_custom_{cs_idx}_{item_idx}_{b_idx}",
                            category="quantifying_impact",
                            severity="suggestion",
                            title=f"Poin pada '{cs.heading}' Belum Memiliki Metrik",
                            description=f"Poin pada bagian '{cs.heading}' akan lebih meyakinkan jika menyertakan dampak kuantitatif.",
                            section_name=f"{cs.heading} — {item.title or ''}",
                            target_text=bullet,
                            suggestion="Tambahkan angka seperti jumlah peserta, anggota tim yang dipimpin, atau jam pelatihan.",
                            needs_user_context=True,
                            context_question=f"Berapa estimasi angka hasil/peserta/skala untuk poin: \"{bullet[:80]}...\"?",
                            context_field_id=field_id
                        ))

        if total_bullets == 0:
            return issues, 100.0
        
        ratio = quantified_bullets / total_bullets
        score = round(max(30.0, min(100.0, ratio * 100.0)), 1)
        return issues, score

    def _check_repetition(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Detect repetitive opening verbs and overused action words."""
        issues: List[ATSDiagnosticIssue] = []
        starting_verbs: Dict[str, List[str]] = {}

        def extract_start_verb(text: str) -> Optional[str]:
            words = text.strip().split()
            if not words:
                return None
            first = words[0].lower().strip('•-*(),.')
            # Skip articles or prepositions
            if first in {"a", "an", "the", "in", "on", "for", "with"}:
                return words[1].lower().strip('•-*(),.') if len(words) > 1 else None
            return first

        # Collect start verbs from experience and projects
        for exp in resume.experience:
            for b in exp.highlights:
                v = extract_start_verb(b)
                if v and len(v) >= 3:
                    starting_verbs.setdefault(v, []).append(b)

        for proj in resume.projects:
            for b in proj.highlights:
                v = extract_start_verb(b)
                if v and len(v) >= 3:
                    starting_verbs.setdefault(v, []).append(b)

        # Flag any verb repeated >= 2 times
        repetition_count = 0
        for verb, occurrences in starting_verbs.items():
            if len(occurrences) >= 2:
                repetition_count += (len(occurrences) - 1)
                alts = POWER_VERB_ALTERNATIVES.get(verb, ["Architected", "Spearheaded", "Engineered", "Orchestrated", "Implemented"])
                issues.append(ATSDiagnosticIssue(
                    id=f"rep_{verb}",
                    category="repetition",
                    severity="warning",
                    title=f"Pengulangan Kata Kerja: '{verb.capitalize()}' Digunakan {len(occurrences)}x",
                    description=(
                        f"Kata kerja pembuka '{verb.capitalize()}' digunakan berulang kali ({len(occurrences)} kali) di awal poin. "
                        "Variasikan kata kerja tindakan agar resume terkesan dinamis dan kaya kosakata kepemimpinan teknis."
                    ),
                    section_name="Work Experience & Projects",
                    target_text=f"Digunakan pada {len(occurrences)} bullet points, contoh: \"{occurrences[0][:75]}...\"",
                    suggestion=f"Ganti beberapa kemunculan dengan variasi power verb: {', '.join(alts[:4])}.",
                    needs_user_context=False
                ))

        score = max(50.0, round(100.0 - (repetition_count * 15.0), 1))
        return issues, score

    def _check_spelling_and_grammar(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Detect common spelling, capitalization, and formatting quality issues."""
        issues: List[ATSDiagnosticIssue] = []
        typo_count = 0

        # Check Summary
        if resume.summary:
            if resume.summary[0].islower():
                typo_count += 1
                issues.append(ATSDiagnosticIssue(
                    id="sg_sum_case",
                    category="spelling_grammar",
                    severity="warning",
                    title="Summary Dimulai dengan Huruf Kecil",
                    description="Professional Summary sebaiknya diawali dengan huruf kapital yang tegas.",
                    section_name="Professional Summary",
                    target_text=resume.summary[:80],
                    suggestion="Gunakan huruf kapital di awal kalimat.",
                    needs_user_context=False
                ))
            if "  " in resume.summary:
                typo_count += 1
                issues.append(ATSDiagnosticIssue(
                    id="sg_sum_double_space",
                    category="spelling_grammar",
                    severity="suggestion",
                    title="Terdapat Spasi Ganda pada Summary",
                    description="Ditemukan spasi ganda (double-space) yang dapat mengurangi kerapian format ATS.",
                    section_name="Professional Summary",
                    target_text=resume.summary[:80],
                    suggestion="Hapus spasi ganda.",
                    needs_user_context=False
                ))

        # Check Experience & Projects highlights
        all_bullets = []
        for exp in resume.experience:
            for b in exp.highlights:
                all_bullets.append((f"Experience — {exp.company}", b))
        for proj in resume.projects:
            for b in proj.highlights:
                all_bullets.append((f"Projects — {proj.name}", b))

        for idx, (sec_name, b) in enumerate(all_bullets):
            clean_b = b.strip()
            if not clean_b:
                continue
            
            # Lowercase start
            if clean_b[0].islower():
                typo_count += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"sg_lower_{idx}",
                    category="spelling_grammar",
                    severity="warning",
                    title="Bullet Point Dimulai Huruf Kecil",
                    description="Setiap bullet point harus diawali dengan huruf kapital.",
                    section_name=sec_name,
                    target_text=clean_b[:75],
                    suggestion=f"Ubah '{clean_b[0]}' menjadi '{clean_b[0].upper()}'.",
                    needs_user_context=False
                ))

            # Double spaces
            if "  " in clean_b:
                typo_count += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"sg_dspace_{idx}",
                    category="spelling_grammar",
                    severity="suggestion",
                    title="Terdapat Spasi Berlebih",
                    description="Ditemukan spasi ganda pada bullet point.",
                    section_name=sec_name,
                    target_text=clean_b[:75],
                    suggestion="Rapikan spasi antar kata.",
                    needs_user_context=False
                ))

            # Stray repetitive punctuation e.g. .., ,,
            if re.search(r'[,\.]{2,}', clean_b) and "..." not in clean_b:
                typo_count += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"sg_punct_{idx}",
                    category="spelling_grammar",
                    severity="warning",
                    title="Tanda Baca Ganda Tidak Baku",
                    description="Ditemukan tanda koma atau titik berulang (misal '..' atau ',,').",
                    section_name=sec_name,
                    target_text=clean_b[:75],
                    suggestion="Gunakan tanda baca tunggal yang konsisten.",
                    needs_user_context=False
                ))

        score = max(55.0, round(100.0 - (typo_count * 9.0), 1))
        return issues, score

    def _check_bullets_consistency(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Detect inconsistent bullet lengths, missing periods, or improper bullet densities."""
        issues: List[ATSDiagnosticIssue] = []
        flaws = 0

        all_bullets = []
        for exp in resume.experience:
            all_bullets.extend([(f"Experience — {exp.company}", b) for b in exp.highlights])
            if len(exp.highlights) > 6:
                flaws += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"bc_count_{exp.company}",
                    category="bullets_consistency",
                    severity="warning",
                    title=f"Terlalu Banyak Bullet Points di {exp.company}",
                    description=f"Posisi ini memiliki {len(exp.highlights)} bullet point. Standar ATS menyarankan maksimal 4–5 bullet paling berdampak agar CV tidak sesak.",
                    section_name=f"Experience — {exp.company}",
                    suggestion="Pilih 3–4 pencapaian terkuat yang paling relevan dengan pekerjaan target.",
                    needs_user_context=False
                ))

        for proj in resume.projects:
            all_bullets.extend([(f"Projects — {proj.name}", b) for b in proj.highlights])
            if len(proj.highlights) > 4:
                flaws += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"bc_pcount_{proj.name}",
                    category="bullets_consistency",
                    severity="warning",
                    title=f"Jumlah Bullet Proyek Melebihi Rekomendasi",
                    description=f"Proyek '{proj.name}' memiliki {len(proj.highlights)} bullet point. Rekomendasi ATS adalah 2–3 bullet padat per proyek.",
                    section_name=f"Projects — {proj.name}",
                    suggestion="Fokuskan pada arsitektur teknis dan hasil metrik terpenting.",
                    needs_user_context=False
                ))

        # Check ending punctuation consistency (period vs no period)
        ended_with_period = [b for _, b in all_bullets if b.strip().endswith('.')]
        ended_without_period = [b for _, b in all_bullets if not b.strip().endswith('.')]

        if ended_with_period and ended_without_period:
            flaws += 1
            issues.append(ATSDiagnosticIssue(
                id="bc_period_mismatch",
                category="bullets_consistency",
                severity="warning",
                title="Tanda Baca Akhir Bullet Tidak Konsisten",
                description=(
                    f"Sebagian bullet diakhiri titik ({len(ended_with_period)} poin) dan sebagian lagi tidak ({len(ended_without_period)} poin). "
                    "ATS checker mendeteksi inkonsistensi tipografi ini."
                ),
                section_name="Experience & Projects",
                suggestion="Seragamkan seluruh akhir bullet point dengan tanda titik (.).",
                needs_user_context=False
            ))

        # Check extreme lengths
        for sec_name, b in all_bullets:
            clean_b = b.strip()
            if len(clean_b) < 30:
                flaws += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"bc_too_short_{hash(clean_b)}",
                    category="bullets_consistency",
                    severity="suggestion",
                    title="Bullet Point Terlalu Singkat",
                    description=f"Poin ini hanya {len(clean_b)} karakter, kurang memberikan konteks peran dan dampak nyata.",
                    section_name=sec_name,
                    target_text=clean_b,
                    suggestion="Kembangkan poin ini dengan formula X-Y-Z (tindakan + dampak + metode teknis).",
                    needs_user_context=False
                ))
            elif len(clean_b) > 280:
                flaws += 1
                issues.append(ATSDiagnosticIssue(
                    id=f"bc_too_long_{hash(clean_b)}",
                    category="bullets_consistency",
                    severity="warning",
                    title="Bullet Point Terlalu Panjang (Membentuk Paragraf)",
                    description=f"Poin ini sepanjang {len(clean_b)} karakter. Bullet yang melebihi 2–3 baris sulit dipindai dengan cepat oleh recruiter.",
                    section_name=sec_name,
                    target_text=clean_b[:80] + "...",
                    suggestion="Pecah menjadi 2 kalimat atau persingkat fokus pada hasil intinya.",
                    needs_user_context=False
                ))

        score = max(60.0, round(100.0 - (flaws * 10.0), 1))
        return issues, score

    def _check_parse_rate(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Verify ATS parseability and contact accessibility."""
        issues: List[ATSDiagnosticIssue] = []
        score = 100.0

        if not resume.contact.email or "@" not in resume.contact.email:
            score -= 20.0
            issues.append(ATSDiagnosticIssue(
                id="pr_no_email",
                category="parse_rate",
                severity="error",
                title="Format Email Tidak Valid",
                description="Email kontak tidak ditemukan atau memiliki format tidak valid.",
                section_name="Contact Information",
                suggestion="Sertakan alamat email profesional yang valid.",
                needs_user_context=False
            ))

        if not resume.contact.phone:
            score -= 10.0
            issues.append(ATSDiagnosticIssue(
                id="pr_no_phone",
                category="parse_rate",
                severity="warning",
                title="Nomor Telepon Tidak Ditemukan",
                description="Nomor kontak penting untuk parsing recruiter ATS.",
                section_name="Contact Information",
                suggestion="Tambahkan nomor telepon aktif dengan kode negara.",
                needs_user_context=False
            ))

        return issues, max(50.0, score)

    def _check_sections(self, resume: TailoredResume) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Verify essential resume sections are populated and well-structured."""
        issues: List[ATSDiagnosticIssue] = []
        score = 100.0

        if not resume.summary or len(resume.summary.strip()) < 40:
            score -= 15.0
            issues.append(ATSDiagnosticIssue(
                id="sec_short_summary",
                category="sections",
                severity="warning",
                title="Professional Summary Belum Memadai",
                description="Ringkasan profesional terlalu singkat atau kosong.",
                section_name="Professional Summary",
                suggestion="Tuliskan 2–3 kalimat yang menyoroti keahlian inti dan kesesuaian peran target.",
                needs_user_context=False
            ))

        if not resume.skills or len(resume.skills) == 0:
            score -= 25.0
            issues.append(ATSDiagnosticIssue(
                id="sec_no_skills",
                category="sections",
                severity="error",
                title="Bagian Technical Skills Kosong",
                description="Daftar keahlian teknis wajib ada untuk scanning kata kunci ATS.",
                section_name="Technical Skills",
                suggestion="Tambahkan kategori keahlian teknis (bahasa pemrograman, tools, framework).",
                needs_user_context=False
            ))

        if not resume.experience or len(resume.experience) == 0:
            score -= 30.0
            issues.append(ATSDiagnosticIssue(
                id="sec_no_exp",
                category="sections",
                severity="error",
                title="Riwayat Pengalaman Kerja Kosong",
                description="Pengalaman kerja adalah bagian utama yang dievaluasi ATS.",
                section_name="Work Experience",
                suggestion="Sertakan riwayat pekerjaan atau pengalaman magang yang relevan.",
                needs_user_context=False
            ))

        if not resume.education or len(resume.education) == 0:
            score -= 15.0
            issues.append(ATSDiagnosticIssue(
                id="sec_no_edu",
                category="sections",
                severity="warning",
                title="Riwayat Pendidikan Kosong",
                description="Riwayat pendidikan formal atau sertifikasi belum terisi.",
                section_name="Education",
                suggestion="Cantumkan institusi, gelar, dan jurusan studi Anda.",
                needs_user_context=False
            ))

        return issues, max(40.0, score)

    def _check_keywords(self, resume: TailoredResume, job: JobListing) -> Tuple[List[ATSDiagnosticIssue], float]:
        """Evaluate alignment against job description keywords."""
        issues: List[ATSDiagnosticIssue] = []
        
        job_text = f"{job.title} {job.description} {' '.join(job.requirements)}"
        job_kws = extract_keywords(job_text, max_keywords=30)
        
        resume_text = (
            f"{resume.summary} " +
            " ".join([f"{c.category} {' '.join(c.skills)}" for c in resume.skills]) +
            " ".join([f"{e.position} {e.company} {' '.join(e.highlights)}" for e in resume.experience]) +
            " ".join([f"{p.name} {p.description} {' '.join(p.highlights)}" for p in resume.projects])
        )
        resume_tokens = set(clean_and_tokenize(resume_text))

        matched = [k for k in job_kws if k in resume_tokens or any(k in t for t in resume_tokens)]
        missing = [k for k in job_kws if k not in matched]

        total = len(job_kws)
        score = (len(matched) / total * 100.0) if total > 0 else 100.0
        score = round(min(100.0, max(0.0, score)), 1)

        if missing and score < 75.0:
            top_missing = missing[:6]
            issues.append(ATSDiagnosticIssue(
                id="kw_missing",
                category="keywords",
                severity="warning",
                title=f"Kata Kunci Lowongan Belum Termasuk ({len(missing)} kata)",
                description=f"Kata kunci penting dari lowongan belum terdeteksi di CV: {', '.join(top_missing)}.",
                section_name="Target Keywords Alignment",
                suggestion=f"Sertakan kata kunci seperti '{', '.join(top_missing[:3])}' pada ringkasan atau keahlian teknis Anda.",
                needs_user_context=False
            ))

        return issues, score
