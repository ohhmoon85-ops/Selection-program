"""
한영자장학재단 장학생 선발 시스템 — Vercel Flask REST API
후원사: 삼양 | 수여식: 2026년 4월 30일
이사장: 전동진 | 사무국장: 임재영

Vercel 서버리스 함수로 배포되는 Flask WSGI 백엔드.
모든 선발 로직(파싱·채점·선발)을 포함한다.
"""

import io
import os
import re
import math
import zipfile
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader   # 순수 Python PDF 파서 (Vercel 서버리스 호환)
from flask import Flask, jsonify, request

# ──────────────────────────────────────────────────────────────────────
# Flask 앱 설정
# ──────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

# CORS — 개발 환경에서도 동작하도록 모든 요청에 헤더 추가
@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response

@app.route("/api/upload", methods=["OPTIONS"])
@app.route("/api/demo",   methods=["OPTIONS"])
def _preflight():
    return "", 204

# ── 루트: public/index.html 서빙 ──────────────────────────────────────
# Vercel은 정적 파일을 별도 빌더 없이 찾지 못하므로 Flask가 직접 반환한다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 프로젝트 루트

@app.route("/")
def serve_index():
    html_path = os.path.join(_ROOT, "public", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}

# ──────────────────────────────────────────────────────────────────────
# 로깅 (처리 이력 — 투명성 원칙)
# ──────────────────────────────────────────────────────────────────────
_log_buf = io.StringIO()
_handler = logging.StreamHandler(_log_buf)
_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
logger = logging.getLogger("hanyang_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_handler)

def _flush_log() -> str:
    """로그 버퍼를 읽고 초기화하여 반환"""
    content = _log_buf.getvalue()
    _log_buf.truncate(0)
    _log_buf.seek(0)
    return content

# ──────────────────────────────────────────────────────────────────────
# 전역 상수
# ──────────────────────────────────────────────────────────────────────
GRADE_SCORES: Dict[int, int] = {4: 50, 3: 35, 2: 20, 1: 5}
MAX_SCHOLARS: int = 50
DEFAULT_GRAD_CREDITS: float = 120.0

STEM_KEYWORDS = [
    "공학", "이학", "전자", "기계", "컴퓨터", "소프트웨어", "정보",
    "국방", "방산", "항공", "우주", "화학", "물리", "수학",
    "전기", "통신", "로봇", "자동화", "반도체", "에너지",
    "재료", "토목", "건축", "환경", "생명", "바이오",
    "인공지능", "AI", "데이터", "사이버", "보안", "국방공학",
    "방위산업", "드론", "무기체계", "레이더", "탄약",
]
CERT_KEYWORDS = [
    "국가기술자격", "국가전문자격",
    "기사", "산업기사", "기능사", "기능장", "기술사",
    "TOEIC", "TOEFL", "IELTS", "OPIc", "JLPT", "HSK",
    "토익", "토플", "오픽", "텝스", "TEPS",
    "자격증", "면허", "어학성적",
]
VOLUNTEER_KEYWORDS = ["봉사", "자원봉사", "사회봉사", "봉사활동", "봉사시간"]
MILITARY_KEYWORDS  = ["병역", "현역", "예비역", "만기전역", "군필", "복무완료", "전역", "군복무"]
DOC_ELIGIBILITY_KW = ["자립지원 대상자 확인서", "자립지원대상자확인서", "자립준비청년 확인서"]
DOC_ENROLLMENT_KW  = ["재학증명서", "재학 증명서"]
DOC_TRANSCRIPT_KW  = ["성적증명서", "성적표", "학업성적", "성적 증명서"]

# ──────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ApplicantData:
    applicant_key: str = ""
    name: str = "미확인"
    grade: int = 0
    major: str = ""
    completed_credits: float = 0.0
    graduation_credits: float = DEFAULT_GRAD_CREDITS
    gpa: float = 0.0
    has_certificate: bool = False
    volunteer_hours: float = 0.0
    is_military: bool = False
    is_eligible: bool = False
    has_enrollment: bool = False
    has_transcript: bool = False
    has_bonus_doc: bool = False
    raw_texts: Dict[str, str] = field(default_factory=dict)
    parse_notes: List[str] = field(default_factory=list)
    # 점수 (ScoringEngine이 채움)
    grade_score: float = 0.0
    completion_rate: float = 0.0
    completion_score: float = 0.0
    bonus_stem: bool = False
    bonus_cert: bool = False
    bonus_volunteer: bool = False
    bonus_score: float = 0.0
    total_score: float = 0.0

# ──────────────────────────────────────────────────────────────────────
# 민감 정보 마스킹 (개인정보보호법 준수)
# ──────────────────────────────────────────────────────────────────────
def mask_sensitive(text: str) -> str:
    """주민번호·전화번호·계좌번호 마스킹"""
    text = re.sub(r"(\d{6})\s*[-–]\s*(\d{7})", r"\1-*******", text)
    text = re.sub(r"(\d{6})(\d{7})", r"\1*******", text)
    text = re.sub(r"(01\d)\s*[-–]\s*(\d{3,4})\s*[-–]\s*(\d{4})", r"\1-****-\3", text)
    text = re.sub(r"(\d{3,4})\s*[-–]\s*(\d{4,6})\s*[-–]\s*(\d{4,7})", r"\1-******-\3", text)
    return text

# ──────────────────────────────────────────────────────────────────────
# PDF 파서
# ──────────────────────────────────────────────────────────────────────
class PDFParser:
    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            pages  = [page.extract_text() or "" for page in reader.pages]
            return mask_sensitive("\n".join(pages))
        except Exception as e:
            logger.warning(f"PDF 추출 실패: {e}")
            return ""

    @staticmethod
    def classify(text: str) -> str:
        if any(k in text for k in DOC_ELIGIBILITY_KW): return "eligibility"
        if any(k in text for k in DOC_ENROLLMENT_KW):  return "enrollment"
        if any(k in text for k in DOC_TRANSCRIPT_KW):  return "transcript"
        if (any(k in text for k in CERT_KEYWORDS)
                or any(k in text for k in VOLUNTEER_KEYWORDS)
                or any(k in text for k in MILITARY_KEYWORDS)):
            return "bonus"
        return "unknown"

    @staticmethod
    def extract_name(text: str) -> Optional[str]:
        for p in [r"성\s*명\s*[：:]\s*([가-힣]{2,5})",
                  r"이\s*름\s*[：:]\s*([가-힣]{2,5})",
                  r"학생명\s*[：:]\s*([가-힣]{2,5})"]:
            m = re.search(p, text)
            if m: return m.group(1).strip()
        return None

    @staticmethod
    def extract_grade(text: str) -> Optional[int]:
        for p in [r"([1-4])\s*학년", r"학\s*년\s*[：:\s]*([1-4])"]:
            m = re.search(p, text)
            if m:
                g = int(m.group(1))
                if 1 <= g <= 4: return g
        return None

    @staticmethod
    def extract_major(text: str) -> Optional[str]:
        for p in [r"전\s*공\s*[：:\s]+([^\n\r\t]{2,30})",
                  r"학\s*과\s*[：:\s]+([^\n\r\t]{2,30})",
                  r"학\s*부\s*[：:\s]+([^\n\r\t]{2,30})"]:
            m = re.search(p, text)
            if m:
                v = re.sub(r"\s+", " ", m.group(1)).strip()
                if 2 <= len(v) <= 40: return v
        return None

    @staticmethod
    def extract_credits(text: str) -> Tuple[Optional[float], Optional[float]]:
        grad = None
        for p in [r"졸업\s*기준\s*학점\s*[：:\s]*(\d+\.?\d*)",
                  r"졸업\s*이수\s*학점\s*[：:\s]*(\d+\.?\d*)",
                  r"졸업\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m = re.search(p, text)
            if m: grad = float(m.group(1)); break

        comp = None
        for p in [r"취득\s*학점\s*[：:\s]*(\d+\.?\d*)",
                  r"이수\s*학점\s*[：:\s]*(\d+\.?\d*)",
                  r"누적\s*학점\s*[：:\s]*(\d+\.?\d*)"]:
            m = re.search(p, text)
            if m: comp = float(m.group(1)); break
        return comp, grad

    @staticmethod
    def extract_gpa(text: str) -> Optional[float]:
        for p in [r"전체\s*평점\s*[：:\s]*(\d+\.\d+)",
                  r"누적\s*평점\s*[：:\s]*(\d+\.\d+)",
                  r"평\s*점\s*[：:\s]*(\d+\.\d+)",
                  r"GPA\s*[：:\s]*(\d+\.\d+)"]:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                v = float(m.group(1))
                if 0.0 <= v <= 4.5: return v
        return None

    @staticmethod
    def check_certificate(text: str) -> bool:
        return any(k.lower() in text.lower() for k in CERT_KEYWORDS)

    @staticmethod
    def extract_volunteer_hours(text: str) -> float:
        for p in [r"봉사\s*시간\s*[：:\s]*(\d+\.?\d*)",
                  r"총\s*봉사\s*[：:\s]*(\d+\.?\d*)\s*시간",
                  r"(\d+\.?\d*)\s*시간"]:
            ms = re.findall(p, text)
            if ms:
                h = max(float(x) for x in ms)
                if 0 < h < 10_000: return h
        return 0.0

    @staticmethod
    def check_military(text: str) -> bool:
        return any(k in text for k in MILITARY_KEYWORDS)

# ──────────────────────────────────────────────────────────────────────
# 점수 계산 엔진
# ──────────────────────────────────────────────────────────────────────
class ScoringEngine:
    @staticmethod
    def calculate(a: ApplicantData) -> ApplicantData:
        # ① 학년 점수
        a.grade_score = float(GRADE_SCORES.get(a.grade, 0))
        # ② 학업 이수율
        if a.graduation_credits > 0:
            rate = min(a.completed_credits / a.graduation_credits, 1.0)
            a.completion_rate  = rate
            a.completion_score = round(rate * 50, 2)
        # ③ 가산점
        bonus = 0
        a.bonus_stem     = any(k in a.major for k in STEM_KEYWORDS)
        a.bonus_cert     = a.has_certificate
        a.bonus_volunteer = a.volunteer_hours >= 50.0
        if a.bonus_stem:      bonus += 5
        if a.bonus_cert:      bonus += 3
        if a.bonus_volunteer: bonus += 2
        a.bonus_score  = float(min(bonus, 10))
        a.total_score  = round(a.grade_score + a.completion_score + a.bonus_score, 2)
        logger.info(
            f"[점수] {a.name:6s} 학년={a.grade_score:.0f} "
            f"이수율={a.completion_score:.2f} 가산={a.bonus_score:.0f} "
            f"→ 총점={a.total_score:.2f}"
        )
        return a

# ──────────────────────────────────────────────────────────────────────
# ZIP 처리기
# ──────────────────────────────────────────────────────────────────────
class DocumentProcessor:
    def __init__(self):
        self._p = PDFParser()
        self._s = ScoringEngine()

    def process(self, zip_bytes: bytes) -> List[ApplicantData]:
        applicants: Dict[str, ApplicantData] = {}

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            logger.info(f"ZIP 열기 — 내부 파일 {len(names)}개")

            for filepath in names:
                if not filepath.lower().endswith(".pdf"): continue
                if "__MACOSX" in filepath: continue

                key  = self._key(filepath)
                if key not in applicants:
                    applicants[key] = ApplicantData(applicant_key=key, name=key)
                a = applicants[key]

                try:
                    text = self._p.extract_text(zf.read(filepath))
                    if not text.strip():
                        a.parse_notes.append(f"⚠ '{filepath}': 텍스트 추출 불가")
                        continue
                    doc_type = self._p.classify(text)
                    a.raw_texts[doc_type] = a.raw_texts.get(doc_type, "") + "\n" + text
                    self._apply(a, doc_type, text)
                    logger.info(f"파싱: {filepath} → [{doc_type}]")
                except Exception as e:
                    a.parse_notes.append(f"❌ '{filepath}': {e}")
                    logger.error(f"오류 ({filepath}): {e}")

        # 실명 보정
        for a in applicants.values():
            for text in a.raw_texts.values():
                name = self._p.extract_name(text)
                if name: a.name = name; break

        # 점수 계산
        results = []
        for a in applicants.values():
            if not a.is_eligible:
                a.parse_notes.insert(0, "⛔ 자립지원 대상자 확인서 미확인 — 제외")
                logger.warning(f"자격 미달: {a.name}")
            self._s.calculate(a)
            results.append(a)

        logger.info(
            f"처리 완료 — 전체 {len(results)}명 / "
            f"자격 충족 {sum(1 for a in results if a.is_eligible)}명"
        )
        return results

    @staticmethod
    def _key(filepath: str) -> str:
        parts = filepath.replace("\\", "/").split("/")
        if len(parts) >= 2: return parts[0].strip()
        base = os.path.splitext(parts[0])[0]
        for sep in ("_", "-", " "):
            if sep in base: return base.split(sep)[0].strip()
        return base.strip()

    def _apply(self, a: ApplicantData, doc_type: str, text: str):
        if doc_type == "eligibility":
            a.is_eligible = True
        elif doc_type == "enrollment":
            a.has_enrollment = True
            g = self._p.extract_grade(text);  a.grade = g if g else a.grade
            m = self._p.extract_major(text);  a.major = m if m else a.major
        elif doc_type == "transcript":
            a.has_transcript = True
            comp, grad = self._p.extract_credits(text)
            if comp is not None: a.completed_credits  = comp
            if grad is not None: a.graduation_credits = grad
            gpa = self._p.extract_gpa(text)
            if gpa is not None: a.gpa = gpa
            if a.grade == 0:
                g = self._p.extract_grade(text)
                if g: a.grade = g
            if not a.major:
                m = self._p.extract_major(text)
                if m: a.major = m
        elif doc_type == "bonus":
            a.has_bonus_doc = True
            if self._p.check_certificate(text): a.has_certificate = True
            h = self._p.extract_volunteer_hours(text)
            if h > 0: a.volunteer_hours = max(a.volunteer_hours, h)
            if self._p.check_military(text): a.is_military = True
        else:
            # 미분류: 모든 필드 시도
            if any(k in text for k in DOC_ELIGIBILITY_KW): a.is_eligible = True
            if a.grade == 0:
                g = self._p.extract_grade(text)
                if g: a.grade = g
            if not a.major:
                m = self._p.extract_major(text)
                if m: a.major = m
            comp, grad = self._p.extract_credits(text)
            if comp and a.completed_credits == 0:  a.completed_credits  = comp
            if grad: a.graduation_credits = grad
            gpa = self._p.extract_gpa(text)
            if gpa and a.gpa == 0: a.gpa = gpa
            if self._p.check_certificate(text): a.has_certificate = True
            h = self._p.extract_volunteer_hours(text)
            if h > 0: a.volunteer_hours = max(a.volunteer_hours, h)
            if self._p.check_military(text): a.is_military = True

# ──────────────────────────────────────────────────────────────────────
# 선발 함수 (동점자 처리 포함)
# ──────────────────────────────────────────────────────────────────────
def select_scholars(
    applicants: List[ApplicantData], n: int = MAX_SCHOLARS
) -> Tuple[List[Dict], List[Dict]]:
    """
    자격자를 정렬하여 상위 n명 선발.
    반환: (선발자 목록, 전체 자격자 목록) — 각 요소는 JSON-safe dict
    """
    eligible = [a for a in applicants if a.is_eligible]
    if not eligible:
        return [], []

    records = []
    for a in eligible:
        records.append({
            "성명":       a.name,
            "학년":       f"{a.grade}학년" if a.grade > 0 else "미확인",
            "_학년숫자":  a.grade,
            "전공":       a.major or "미확인",
            "이수학점":   a.completed_credits,
            "졸업기준학점": a.graduation_credits,
            "이수율":     round(a.completion_rate * 100, 1),
            "_이수율정렬": a.completion_rate,
            "GPA":        a.gpa,
            "학년점수":   a.grade_score,
            "이수율점수": a.completion_score,
            "가산점":     a.bonus_score,
            "총점":       a.total_score,
            "이공계방산": "✓" if a.bonus_stem     else "",
            "자격증어학": "✓" if a.bonus_cert     else "",
            "봉사50h":   "✓" if a.bonus_volunteer else "",
            "자립확인서": "✓" if a.is_eligible    else "✗",
            "재학증명서": "✓" if a.has_enrollment else "미확인",
            "성적증명서": "✓" if a.has_transcript else "미확인",
            "비고":       " | ".join(a.parse_notes) if a.parse_notes else "정상 처리",
        })

    # 정렬: 총점↓ → 이수율↓ → 학년↓ → GPA↓
    records.sort(
        key=lambda r: (r["총점"], r["_이수율정렬"], r["_학년숫자"], r["GPA"]),
        reverse=True,
    )

    # 순위 부여 및 정렬용 숨김 필드 제거
    all_list = []
    for rank, rec in enumerate(records, 1):
        rec["순위"] = rank
        rec.pop("_학년숫자", None)
        rec.pop("_이수율정렬", None)
        all_list.append(rec)

    selected = all_list[:n]
    logger.info(f"최종 선발: 자격자 {len(eligible)}명 중 {len(selected)}명")
    return selected, all_list

# ──────────────────────────────────────────────────────────────────────
# 통계 리포트
# ──────────────────────────────────────────────────────────────────────
def build_report(selected: List[Dict], total_applicants: int) -> Dict[str, Any]:
    if not selected:
        return {}
    n = len(selected)
    scores     = [r["총점"]     for r in selected]
    comp_rates = [r["이수율"]   for r in selected]
    gpas       = [r["GPA"]      for r in selected]
    grade_dist: Dict[str, int] = {}
    for r in selected:
        grade_dist[r["학년"]] = grade_dist.get(r["학년"], 0) + 1

    stem_n  = sum(1 for r in selected if r["이공계방산"] == "✓")
    cert_n  = sum(1 for r in selected if r["자격증어학"] == "✓")
    vol_n   = sum(1 for r in selected if r["봉사50h"]   == "✓")

    return {
        "total_applicants": total_applicants,
        "selected_count":   n,
        "selection_rate":   round(n / total_applicants * 100, 1) if total_applicants else 0,
        "avg_score":  round(sum(scores) / n, 2),
        "max_score":  round(max(scores), 2),
        "min_score":  round(min(scores), 2),
        "avg_completion": round(sum(comp_rates) / n, 1),
        "avg_gpa":    round(sum(gpas) / n, 2),
        "grade_dist": grade_dist,
        "stem_count": stem_n,
        "stem_rate":  round(stem_n / n * 100, 1),
        "cert_count": cert_n,
        "vol_count":  vol_n,
    }

# ──────────────────────────────────────────────────────────────────────
# 데모 데이터 (PDF 없이 테스트)
# ──────────────────────────────────────────────────────────────────────
def make_demo_applicants(n: int = 30) -> List[ApplicantData]:
    random.seed(42)
    names   = ["김민준","이서연","박도윤","최서현","정예은","강지호","조수아","윤민서",
               "장하은","임준혁","오지원","한소율","신재현","권나연","유태양","배수빈",
               "노현우","심지유","문성민","허다은","서지훈","안채원","남기태","고은서",
               "류민호","전수현","양준서","설아린","마지현","제갈민"]
    majors  = ["컴퓨터공학과","전자공학과","기계공학과","국방학과","경영학과",
               "사회복지학과","심리학과","소프트웨어학과","방위산업학과","화학공학과"]
    results = []
    for i in range(n):
        a = ApplicantData(
            applicant_key=f"demo_{i}",
            name=names[i % len(names)],
            grade=random.randint(1, 4),
            major=majors[random.randint(0, len(majors) - 1)],
            completed_credits=round(random.uniform(10, 135), 1),
            graduation_credits=random.choice([120.0, 130.0, 140.0]),
            gpa=round(random.uniform(1.5, 4.3), 2),
            has_certificate=random.random() > 0.5,
            volunteer_hours=random.choice([0, 20, 55, 80, 100]),
            is_eligible=random.random() > 0.1,
            has_enrollment=True,
            has_transcript=True,
        )
        ScoringEngine.calculate(a)
        results.append(a)
    return results

# ──────────────────────────────────────────────────────────────────────
# JSON 직렬화 헬퍼 (NaN/Inf 처리)
# ──────────────────────────────────────────────────────────────────────
def _clean(obj: Any) -> Any:
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

# ──────────────────────────────────────────────────────────────────────
# API 엔드포인트
# ──────────────────────────────────────────────────────────────────────
@app.route("/api/upload", methods=["POST"])
def upload_zip():
    """ZIP 파일 업로드 → 파싱 → 채점 → 선발 결과 반환"""
    _flush_log()

    if "file" not in request.files:
        return jsonify({"success": False, "error": "파일이 없습니다."}), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".zip"):
        return jsonify({"success": False, "error": "ZIP 파일만 허용됩니다."}), 400

    try:
        zip_bytes = f.read()
        if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
            return jsonify({"success": False, "error": "손상된 ZIP 파일입니다."}), 400

        processor = DocumentProcessor()
        applicants = processor.process(zip_bytes)

        if not applicants:
            return jsonify({"success": False, "error": "처리 가능한 신청자가 없습니다."}), 400

        selected, all_eligible = select_scholars(applicants, MAX_SCHOLARS)
        stats    = build_report(selected, len(applicants))
        warnings = [{"name": a.name, "note": " | ".join(a.parse_notes)}
                    for a in applicants if a.parse_notes]

        return jsonify(_clean({
            "success":          True,
            "is_demo":          False,
            "total_applicants": len(applicants),
            "eligible_count":   len(all_eligible),
            "selected_count":   len(selected),
            "results":          selected,
            "all_results":      all_eligible,
            "stats":            stats,
            "warnings":         warnings,
            "log":              _flush_log(),
        }))

    except MemoryError:
        return jsonify({"success": False, "error": "파일이 너무 큽니다."}), 413
    except Exception as e:
        logger.error(f"처리 오류: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/demo", methods=["POST"])
def demo():
    """PDF 없이 더미 데이터로 전체 흐름 시연"""
    _flush_log()
    try:
        applicants  = make_demo_applicants(30)
        selected, all_eligible = select_scholars(applicants, MAX_SCHOLARS)
        stats = build_report(selected, len(applicants))
        return jsonify(_clean({
            "success":          True,
            "is_demo":          True,
            "total_applicants": len(applicants),
            "eligible_count":   len(all_eligible),
            "selected_count":   len(selected),
            "results":          selected,
            "all_results":      all_eligible,
            "stats":            stats,
            "warnings":         [],
            "log":              _flush_log(),
        }))
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})
