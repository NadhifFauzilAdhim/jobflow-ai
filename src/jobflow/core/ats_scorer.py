"""ATS Scoring & Keyword Matching Engine."""

import re
from typing import Set, List, Tuple
from jobflow.core.schema import MasterProfile, TailoredResume, JobListing, ATSAnalysisResult


# Common English & Technical Stop Words
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "experience", "work", "job", "candidate", "role",
    "responsibilities", "requirements", "qualifications", "looking", "team", "company",
    "years", "working", "ability", "strong", "skills", "must", "plus", "preferred"
}


def clean_and_tokenize(text: str) -> List[str]:
    """Tokenize and clean words while keeping technical terms like c++, c#, node.js."""
    # Convert to lowercase
    text = text.lower()
    # Normalize common tech terms
    text = re.sub(r'node\.js', 'nodejs', text)
    text = re.sub(r'vue\.js', 'vuejs', text)
    text = re.sub(r'react\.js', 'react', text)
    text = re.sub(r'next\.js', 'nextjs', text)
    
    # Extract alphanumeric and symbols (+, #)
    tokens = re.findall(r'\b[a-z0-9+#\.\-_]{2,}\b', text)
    return [t for t in tokens if t not in STOP_WORDS and len(t) > 1]


def extract_keywords(text: str, max_keywords: int = 30) -> List[str]:
    """Extract top frequent and relevant keywords from text."""
    tokens = clean_and_tokenize(text)
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
        
    sorted_items = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in sorted_items[:max_keywords]]


def resume_to_text(resume: TailoredResume | MasterProfile) -> str:
    """Flatten resume fields into single searchable text."""
    parts = [
        resume.summary,
        " ".join([f"{cat.category} {' '.join(cat.skills)}" for cat in resume.skills]),
        " ".join([f"{exp.position} {exp.company} {' '.join(exp.highlights)} {' '.join(exp.technologies)}" for exp in resume.experience]),
        " ".join([f"{edu.institution} {edu.degree} {edu.field_of_study} {' '.join(edu.highlights)}" for edu in resume.education]),
        " ".join([f"{proj.name} {proj.description} {' '.join(proj.highlights)} {' '.join(proj.technologies)}" for proj in resume.projects]),
        " ".join(resume.certifications),
    ]
    return " ".join(parts)


def evaluate_ats(resume: TailoredResume | MasterProfile, job: JobListing) -> ATSAnalysisResult:
    """Analyze match percentage and keyword density between resume and job."""
    job_text = f"{job.title} {job.description} {' '.join(job.requirements)}"
    job_keywords = extract_keywords(job_text, max_keywords=35)
    
    resume_text = resume_to_text(resume)
    resume_tokens = set(clean_and_tokenize(resume_text))
    
    matched: List[str] = []
    missing: List[str] = []
    
    for kw in job_keywords:
        if kw in resume_tokens or any(kw in tok for tok in resume_tokens):
            matched.append(kw)
        else:
            missing.append(kw)
            
    total = len(job_keywords)
    score = (len(matched) / total * 100.0) if total > 0 else 100.0
    score = round(min(100.0, max(0.0, score)), 1)
    
    suggestions = []
    if score < 70:
        suggestions.append(f"Incorporate missing core keywords: {', '.join(missing[:5])}")
    if not any(req.lower() in resume_text.lower() for req in job.requirements[:3]):
        suggestions.append("Align your professional summary directly with the top required qualifications.")
    if len(matched) < 10:
        suggestions.append("Highlight specific tech stacks and metrics matching this job description in your bullet points.")
    if not suggestions:
        suggestions.append("Great alignment! Resume matches high-priority job keywords.")
        
    return ATSAnalysisResult(
        score=score,
        matched_keywords=matched,
        missing_keywords=missing,
        suggestions=suggestions
    )
