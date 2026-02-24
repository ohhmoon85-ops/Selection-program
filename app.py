"""
╔══════════════════════════════════════════════════════════════════╗
║         한영자장학재단 장학생 선발 자동화 시스템 v1.0              ║
║         후원사: 삼양 (방산기업) | 수여식: 2026년 4월 30일         ║
║         이사장: 전동진  |  사무국장: 임재영                        ║
╚══════════════════════════════════════════════════════════════════╝

[개요]
  자립준비청년의 대학 졸업을 지원하기 위해 장학생 상위 50명을
  객관적 지표(학년 점수 + 학업 이수율 + 가산점)에 따라 자동 선발.

[선발 기준]
  ① 학년 점수     (최대 50점): 4학년=50, 3학년=35, 2학년=20, 1학년=5
  ② 학업 이수율   (최대 50점): (이수학점 / 졸업기준학점) × 50
  ③ 가산점        (최대 10점): 이공계/방산 전공 +5, 국가자격증/어학 +3, 봉사 50h+ +2
  ④ 동점자 처리              : 이수율 → 상급학년 → GPA 순

[보안]
  주민등록번호 뒷자리, 전화번호, 계좌번호 등 민감 정보 마스킹 처리
"""

# ── 표준 라이브러리 ──────────────────────────────────────────────────
import io
import os
import re
import zipfile
import logging
import tempfile
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

# ── 서드파티 라이브러리 ──────────────────────────────────────────────
import streamlit as st
import pandas as pd
import fitz  # PyMuPDF

# ──────────────────────────────────────────────────────────────────────
# 로깅 설정 — 투명성 원칙: 모든 처리 과정을 이력으로 기록
# ──────────────────────────────────────────────────────────────────────
_log_buffer = io.StringIO()
_log_handler_buf = logging.StreamHandler(_log_buffer)
_log_handler_buf.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
)
logger = logging.getLogger("hanyang_scholarship")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_log_handler_buf)
    logger.addHandler(logging.StreamHandler())


# ──────────────────────────────────────────────────────────────────────
# 전역 상수
# ──────────────────────────────────────────────────────────────────────

# 학년별 기본 점수
GRADE_SCORES: Dict[int, int] = {4: 50, 3: 35, 2: 20, 1: 5}

# 이공계 / 방산 관련 전공 키워드 (가산점 +5)
STEM_KEYWORDS: List[str] = [
    "공학", "이학", "전자", "기계", "컴퓨터", "소프트웨어", "정보",
    "국방", "방산", "항공", "우주", "화학", "물리", "수학",
    "전기", "통신", "로봇", "자동화", "반도체", "에너지",
    "재료", "토목", "건축", "환경", "생명", "바이오",
    "인공지능", "AI", "데이터", "사이버", "보안", "국방공학",
    "방위산업", "드론", "무기체계", "레이더", "탄약",
]

# 국가 자격증 / 어학 성적 키워드 (가산점 +3)
CERT_KEYWORDS: List[str] = [
    "국가기술자격", "국가전문자격",
    "기사", "산업기사", "기능사", "기능장", "기술사",
    "TOEIC", "TOEFL", "IELTS", "OPIc", "JLPT", "HSK",
    "토익", "토플", "오픽", "텝스", "TEPS",
    "자격증", "면허", "어학성적",
]

# 봉사 활동 관련 키워드
VOLUNTEER_KEYWORDS: List[str] = ["봉사", "자원봉사", "사회봉사", "봉사활동", "봉사시간"]

# 병역 관련 키워드
MILITARY_KEYWORDS: List[str] = [
    "병역", "현역", "예비역", "만기전역", "군필", "복무완료",
    "전역", "군복무", "병역이행",
]

# 필수 서류 식별 키워드
DOC_ELIGIBILITY_KW: List[str] = [
    "자립지원 대상자 확인서",
    "자립지원대상자확인서",
    "자립준비청년 확인서",
]
DOC_ENROLLMENT_KW: List[str] = ["재학증명서", "재학 증명서"]
DOC_TRANSCRIPT_KW: List[str] = ["성적증명서", "성적표", "학업성적", "성적 증명서"]

# 최대 선발 인원
MAX_SCHOLARS: int = 50

# 졸업 기준 학점 기본값 (학교별 상이하므로 추출 실패 시 사용)
DEFAULT_GRADUATION_CREDITS: float = 120.0


# ──────────────────────────────────────────────────────────────────────
# 데이터 클래스 — 신청자 1인의 모든 정보를 저장
# ──────────────────────────────────────────────────────────────────────
@dataclass
class ApplicantData:
    """신청자 정보 컨테이너"""

    # ─── 식별 정보
    applicant_key: str = ""          # ZIP 내 폴더/파일 기반 식별자
    name: str = "미확인"             # PDF에서 추출한 실명

    # ─── 학적 정보
    grade: int = 0                   # 학년 (1~4)
    major: str = ""                  # 전공명
    completed_credits: float = 0.0   # 현재 이수 학점
    graduation_credits: float = DEFAULT_GRADUATION_CREDITS  # 졸업 기준 학점
    gpa: float = 0.0                 # 전체 평점 (0.0 ~ 4.5)

    # ─── 가산점 근거
    has_certificate: bool = False    # 자격증/어학 성적 보유
    volunteer_hours: float = 0.0     # 봉사 활동 시간
    is_military: bool = False        # 병역 이행 완료

    # ─── 서류 제출 여부
    is_eligible: bool = False        # 자립지원 대상자 확인서 ✓
    has_enrollment: bool = False     # 재학증명서 ✓
    has_transcript: bool = False     # 성적증명서 ✓
    has_bonus_doc: bool = False      # 가산점 서류 ✓

    # ─── 내부 처리용
    raw_texts: Dict[str, str] = field(default_factory=dict)   # 서류종류 → 추출 텍스트
    parse_notes: List[str] = field(default_factory=list)       # 파싱 경고·메모

    # ─── 점수 계산 결과 (ScoringEngine이 채움)
    grade_score: float = 0.0
    completion_rate: float = 0.0
    completion_score: float = 0.0
    bonus_stem: bool = False
    bonus_cert: bool = False
    bonus_volunteer: bool = False
    bonus_score: float = 0.0
    total_score: float = 0.0


# ──────────────────────────────────────────────────────────────────────
# 민감 정보 마스킹 — 개인정보보호법 준수
# ──────────────────────────────────────────────────────────────────────
def mask_sensitive_info(text: str) -> str:
    """
    PDF 추출 텍스트에서 개인 식별 정보를 마스킹한다.

    처리 대상:
      - 주민등록번호: XXXXXX-XXXXXXX → XXXXXX-*******
      - 전화번호:    010-1234-5678   → 010-****-5678
      - 계좌번호:    XXX-XXXXXX-XXXX → XXX-******-XXXX
    """
    # 주민등록번호 뒷자리 마스킹
    text = re.sub(r"(\d{6})\s*[-–]\s*(\d{7})", r"\1-*******", text)
    text = re.sub(r"(\d{6})(\d{7})", r"\1*******", text)

    # 휴대전화 가운데 4자리 마스킹
    text = re.sub(r"(01\d)\s*[-–]\s*(\d{3,4})\s*[-–]\s*(\d{4})", r"\1-****-\3", text)

    # 계좌번호 마스킹 (XXX-XXXXXX-XXXX 형태)
    text = re.sub(r"(\d{3,4})\s*[-–]\s*(\d{4,6})\s*[-–]\s*(\d{4,7})", r"\1-******-\3", text)

    return text


# ──────────────────────────────────────────────────────────────────────
# PDF 파서 — PyMuPDF 기반 텍스트 추출 및 필드 파싱
# ──────────────────────────────────────────────────────────────────────
class PDFParser:
    """단일 PDF 파일을 파싱하여 구조화된 데이터를 추출한다."""

    # ── 텍스트 추출 ────────────────────────────────────────
    @staticmethod
    def extract_text(pdf_bytes: bytes) -> str:
        """PDF 바이트 → 마스킹된 텍스트 문자열"""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_text = [page.get_text() for page in doc]
            doc.close()
            raw = "\n".join(pages_text)
            return mask_sensitive_info(raw)
        except Exception as exc:
            logger.warning(f"PDF 텍스트 추출 실패: {exc}")
            return ""

    # ── 서류 분류 ───────────────────────────────────────────
    @staticmethod
    def classify(text: str) -> str:
        """
        텍스트 내 키워드로 서류 종류를 판별.

        반환값: 'eligibility' | 'enrollment' | 'transcript' | 'bonus' | 'unknown'
        """
        if any(kw in text for kw in DOC_ELIGIBILITY_KW):
            return "eligibility"
        if any(kw in text for kw in DOC_ENROLLMENT_KW):
            return "enrollment"
        if any(kw in text for kw in DOC_TRANSCRIPT_KW):
            return "transcript"
        # 가산점 서류: 자격증, 봉사, 병역 중 하나라도 포함
        if (
            any(kw in text for kw in CERT_KEYWORDS)
            or any(kw in text for kw in VOLUNTEER_KEYWORDS)
            or any(kw in text for kw in MILITARY_KEYWORDS)
        ):
            return "bonus"
        return "unknown"

    # ── 이름 추출 ───────────────────────────────────────────
    @staticmethod
    def extract_name(text: str) -> Optional[str]:
        """성명 필드에서 한글 이름 추출"""
        patterns = [
            r"성\s*명\s*[：:]\s*([가-힣]{2,5})",
            r"이\s*름\s*[：:]\s*([가-힣]{2,5})",
            r"신청인\s*[：:]\s*([가-힣]{2,5})",
            r"학생명\s*[：:]\s*([가-힣]{2,5})",
            r"학\s*생\s*[：:]\s*([가-힣]{2,5})",
            r"^([가-힣]{2,5})\s+학생",
        ]
        for ptn in patterns:
            m = re.search(ptn, text, re.MULTILINE)
            if m:
                return m.group(1).strip()
        return None

    # ── 학년 추출 ───────────────────────────────────────────
    @staticmethod
    def extract_grade(text: str) -> Optional[int]:
        """현재 학년(1~4) 추출"""
        patterns = [
            r"([1-4])\s*학년",
            r"재학\s*학년\s*[：:\s]*([1-4])",
            r"학\s*년\s*[：:\s]*([1-4])",
            r"Grade\s*[：:\s]*([1-4])",
        ]
        for ptn in patterns:
            m = re.search(ptn, text)
            if m:
                g = int(m.group(1))
                if 1 <= g <= 4:
                    return g
        return None

    # ── 전공 추출 ───────────────────────────────────────────
    @staticmethod
    def extract_major(text: str) -> Optional[str]:
        """학과/전공명 추출"""
        patterns = [
            r"전\s*공\s*[：:\s]+([^\n\r\t]{2,30})",
            r"학\s*과\s*[：:\s]+([^\n\r\t]{2,30})",
            r"학\s*부\s*[：:\s]+([^\n\r\t]{2,30})",
            r"소\s*속\s*[：:\s]+([^\n\r\t]{2,30})",
            r"Department\s*[：:\s]+([^\n\r\t]{2,40})",
        ]
        for ptn in patterns:
            m = re.search(ptn, text)
            if m:
                major = re.sub(r"\s+", " ", m.group(1)).strip()
                # 너무 길거나 짧은 경우 제외
                if 2 <= len(major) <= 40:
                    return major
        return None

    # ── 학점 추출 ───────────────────────────────────────────
    @staticmethod
    def extract_credits(text: str) -> Tuple[Optional[float], Optional[float]]:
        """
        (이수 학점, 졸업 기준 학점) 추출.
        추출 실패 시 해당 값은 None.
        """
        # ① 졸업 기준 학점
        grad_patterns = [
            r"졸업\s*기준\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"졸업\s*이수\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"총\s*졸업\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"졸업\s*학점\s*[：:\s]*(\d+\.?\d*)",
        ]
        graduation: Optional[float] = None
        for ptn in grad_patterns:
            m = re.search(ptn, text)
            if m:
                graduation = float(m.group(1))
                break

        # ② 현재 이수(취득) 학점
        comp_patterns = [
            r"취득\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"이수\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"현재\s*이수\s*[：:\s]*(\d+\.?\d*)",
            r"누적\s*학점\s*[：:\s]*(\d+\.?\d*)",
            r"합\s*계\s*[：:\s]*(\d+\.?\d*)\s*학점",
            r"취득\s*[：:\s]*(\d+\.?\d*)\s*학점",
        ]
        completed: Optional[float] = None
        for ptn in comp_patterns:
            m = re.search(ptn, text)
            if m:
                completed = float(m.group(1))
                break

        return completed, graduation

    # ── GPA 추출 ────────────────────────────────────────────
    @staticmethod
    def extract_gpa(text: str) -> Optional[float]:
        """전체 평점 평균(GPA, 0.0~4.5) 추출"""
        patterns = [
            r"전체\s*평점\s*[：:\s]*(\d+\.\d+)",
            r"누적\s*평점\s*[：:\s]*(\d+\.\d+)",
            r"평\s*점\s*[：:\s]*(\d+\.\d+)",
            r"평균\s*[：:\s]*(\d+\.\d+)",
            r"GPA\s*[：:\s]*(\d+\.\d+)",
        ]
        for ptn in patterns:
            m = re.search(ptn, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                # 일반적 GPA 범위(0.0~4.5) 검증
                if 0.0 <= val <= 4.5:
                    return val
        return None

    # ── 자격증 / 어학 성적 보유 여부 ───────────────────────
    @staticmethod
    def check_certificate(text: str) -> bool:
        """국가 자격증 또는 어학 성적 키워드 존재 여부 확인"""
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in CERT_KEYWORDS)

    # ── 봉사 시간 추출 ──────────────────────────────────────
    @staticmethod
    def extract_volunteer_hours(text: str) -> float:
        """봉사 활동 총 시간 추출 (단위: 시간)"""
        patterns = [
            r"봉사\s*시간\s*[：:\s]*(\d+\.?\d*)",
            r"총\s*봉사\s*[：:\s]*(\d+\.?\d*)\s*시간",
            r"누적\s*봉사\s*[：:\s]*(\d+\.?\d*)",
            r"활동\s*시간\s*[：:\s]*(\d+\.?\d*)",
            r"(\d+\.?\d*)\s*시간",
        ]
        for ptn in patterns:
            matches = re.findall(ptn, text)
            if matches:
                # 가장 큰 값 = 누적 총 시간
                hours = max(float(h) for h in matches)
                # 비정상적으로 큰 값(예: 연도 숫자) 제외
                if 0 < hours < 10_000:
                    return hours
        return 0.0

    # ── 병역 이행 여부 ──────────────────────────────────────
    @staticmethod
    def check_military(text: str) -> bool:
        """병역 이행 완료 키워드 존재 여부 확인"""
        return any(kw in text for kw in MILITARY_KEYWORDS)


# ──────────────────────────────────────────────────────────────────────
# 점수 계산 엔진
# ──────────────────────────────────────────────────────────────────────
class ScoringEngine:
    """ApplicantData를 받아 각 항목별 점수 및 총점을 계산한다."""

    @staticmethod
    def calculate(applicant: ApplicantData) -> ApplicantData:
        """
        점수 계산 후 applicant 객체를 갱신하여 반환.

        ① 학년 점수     (50점 만점)
        ② 학업 이수율   (50점 만점)
        ③ 가산점        (10점 한도)
        """
        # ① 학년 점수
        applicant.grade_score = float(GRADE_SCORES.get(applicant.grade, 0))

        # ② 학업 이수율 점수
        if applicant.graduation_credits > 0:
            rate = min(applicant.completed_credits / applicant.graduation_credits, 1.0)
            applicant.completion_rate = rate
            applicant.completion_score = round(rate * 50, 2)
        else:
            applicant.completion_rate = 0.0
            applicant.completion_score = 0.0

        # ③ 가산점 계산
        bonus = 0

        # 이공계/방산 전공 여부 (+5)
        applicant.bonus_stem = any(kw in applicant.major for kw in STEM_KEYWORDS)
        if applicant.bonus_stem:
            bonus += 5

        # 국가 자격증 또는 어학 성적 (+3)
        applicant.bonus_cert = applicant.has_certificate
        if applicant.bonus_cert:
            bonus += 3

        # 봉사 50시간 이상 (+2)
        applicant.bonus_volunteer = applicant.volunteer_hours >= 50.0
        if applicant.bonus_volunteer:
            bonus += 2

        applicant.bonus_score = float(min(bonus, 10))  # 10점 한도

        # 총점
        applicant.total_score = round(
            applicant.grade_score + applicant.completion_score + applicant.bonus_score, 2
        )

        logger.info(
            f"[점수] {applicant.name!r:8s} │ "
            f"학년({applicant.grade}학년)={applicant.grade_score:4.0f}pt │ "
            f"이수율({applicant.completion_rate*100:.1f}%)={applicant.completion_score:5.2f}pt │ "
            f"가산={applicant.bonus_score:.0f}pt │ "
            f"총점={applicant.total_score:.2f}pt"
        )
        return applicant


# ──────────────────────────────────────────────────────────────────────
# ZIP 처리기 — 압축 파일에서 신청자 데이터를 수집
# ──────────────────────────────────────────────────────────────────────
class DocumentProcessor:
    """
    ZIP 파일을 열어 신청자별 PDF를 파싱하고 점수를 계산한다.

    기대하는 ZIP 구조 (폴더형):
        📦 신청서류.zip
        ├── 홍길동/
        │   ├── 자립지원대상자확인서.pdf
        │   ├── 재학증명서.pdf
        │   ├── 성적증명서.pdf
        │   └── 가산점서류.pdf
        └── 김철수/ ...

    파일명형 구조도 허용:
        홍길동_자립지원대상자확인서.pdf
        홍길동_재학증명서.pdf
    """

    def __init__(self):
        self._parser = PDFParser()
        self._scorer = ScoringEngine()

    def process(self, zip_bytes: bytes) -> List[ApplicantData]:
        """ZIP 바이트를 처리하여 점수가 계산된 ApplicantData 목록 반환"""
        applicants: Dict[str, ApplicantData] = {}

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            logger.info(f"ZIP 파일 열기 완료 — 내부 파일 수: {len(names)}")

            for filepath in names:
                # PDF 파일만 처리
                if not filepath.lower().endswith(".pdf"):
                    continue
                # macOS 메타데이터 폴더 제외
                if "__MACOSX" in filepath:
                    continue

                key = self._to_applicant_key(filepath)

                if key not in applicants:
                    applicants[key] = ApplicantData(applicant_key=key, name=key)

                appl = applicants[key]

                try:
                    pdf_bytes = zf.read(filepath)
                    text = self._parser.extract_text(pdf_bytes)

                    if not text.strip():
                        appl.parse_notes.append(
                            f"⚠ '{filepath}': 텍스트 추출 불가 (스캔 이미지로 추정)"
                        )
                        logger.warning(f"텍스트 없음: {filepath}")
                        continue

                    doc_type = self._parser.classify(text)
                    # 중복 타입 처리: 같은 종류 서류가 여러 개일 경우 내용 합산
                    if doc_type in appl.raw_texts:
                        appl.raw_texts[doc_type] += "\n" + text
                    else:
                        appl.raw_texts[doc_type] = text

                    self._apply_document(appl, doc_type, text)
                    logger.info(f"파싱 완료: {filepath} → [{doc_type}]")

                except Exception as exc:
                    appl.parse_notes.append(f"❌ '{filepath}': 오류 — {exc}")
                    logger.error(f"파싱 오류 ({filepath}): {exc}", exc_info=True)

        # ── 이름 보정: PDF에서 실명 추출 시 파일명 기반 키를 덮어씀
        for appl in applicants.values():
            for text in appl.raw_texts.values():
                real_name = self._parser.extract_name(text)
                if real_name:
                    appl.name = real_name
                    break

        # ── 자격 검증 및 점수 계산
        results: List[ApplicantData] = []
        for appl in applicants.values():
            if not appl.is_eligible:
                appl.parse_notes.insert(
                    0, "⛔ 자립지원 대상자 확인서 미확인 — 선발 대상 제외"
                )
                logger.warning(f"자격 미달: {appl.name!r} (자립확인서 없음)")

            self._scorer.calculate(appl)
            results.append(appl)

        logger.info(
            f"처리 완료 — 총 {len(results)}명 / "
            f"자격 충족: {sum(1 for a in results if a.is_eligible)}명"
        )
        return results

    # ── 내부 헬퍼 ─────────────────────────────────────────

    @staticmethod
    def _to_applicant_key(filepath: str) -> str:
        """파일 경로에서 신청자 구분 키(폴더명 또는 파일명 앞부분) 추출"""
        normalized = filepath.replace("\\", "/")
        parts = normalized.split("/")

        if len(parts) >= 2:
            # 폴더형: 첫 번째 디렉터리를 신청자 키로 사용
            return parts[0].strip()

        # 파일명형: 구분자로 분리
        basename = os.path.splitext(parts[0])[0]
        for sep in ("_", "-", " "):
            if sep in basename:
                return basename.split(sep)[0].strip()
        return basename.strip()

    def _apply_document(
        self, appl: ApplicantData, doc_type: str, text: str
    ) -> None:
        """서류 종류별로 해당 필드를 채운다"""

        if doc_type == "eligibility":
            # ── 자립지원 대상자 확인서
            appl.is_eligible = True
            logger.info(f"자격 확인: {appl.name!r}")

        elif doc_type == "enrollment":
            # ── 재학증명서: 학년, 전공
            appl.has_enrollment = True
            grade = self._parser.extract_grade(text)
            if grade:
                appl.grade = grade
            major = self._parser.extract_major(text)
            if major:
                appl.major = major

        elif doc_type == "transcript":
            # ── 성적증명서: 학점, GPA (학년/전공 보완 추출도 시도)
            appl.has_transcript = True
            completed, graduation = self._parser.extract_credits(text)
            if completed is not None:
                appl.completed_credits = completed
            if graduation is not None:
                appl.graduation_credits = graduation
            gpa = self._parser.extract_gpa(text)
            if gpa is not None:
                appl.gpa = gpa
            # 재학증명서가 없을 경우 학년·전공 보완
            if appl.grade == 0:
                g = self._parser.extract_grade(text)
                if g:
                    appl.grade = g
            if not appl.major:
                m = self._parser.extract_major(text)
                if m:
                    appl.major = m

        elif doc_type == "bonus":
            # ── 가산점 서류: 자격증, 봉사, 병역
            appl.has_bonus_doc = True
            if self._parser.check_certificate(text):
                appl.has_certificate = True
            hours = self._parser.extract_volunteer_hours(text)
            if hours > 0:
                appl.volunteer_hours = max(appl.volunteer_hours, hours)
            if self._parser.check_military(text):
                appl.is_military = True

        else:
            # ── 미분류: 모든 필드 추출 시도 (포괄적 파싱)
            if any(kw in text for kw in DOC_ELIGIBILITY_KW):
                appl.is_eligible = True
            if appl.grade == 0:
                g = self._parser.extract_grade(text)
                if g:
                    appl.grade = g
            if not appl.major:
                m = self._parser.extract_major(text)
                if m:
                    appl.major = m
            completed, graduation = self._parser.extract_credits(text)
            if completed is not None and appl.completed_credits == 0:
                appl.completed_credits = completed
            if graduation is not None:
                appl.graduation_credits = graduation
            gpa = self._parser.extract_gpa(text)
            if gpa is not None and appl.gpa == 0:
                appl.gpa = gpa
            if self._parser.check_certificate(text):
                appl.has_certificate = True
            hours = self._parser.extract_volunteer_hours(text)
            if hours > 0:
                appl.volunteer_hours = max(appl.volunteer_hours, hours)
            if self._parser.check_military(text):
                appl.is_military = True


# ──────────────────────────────────────────────────────────────────────
# 최종 선발 함수 — 동점자 처리 포함
# ──────────────────────────────────────────────────────────────────────
def select_scholars(
    applicants: List[ApplicantData], n: int = MAX_SCHOLARS
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    자격 요건(자립지원 대상자 확인서) 충족자 중 점수 상위 n명을 선발.

    동점자 처리 우선순위:
      1순위: 이수 학점률 (높을수록 우선)
      2순위: 상급 학년  (높을수록 우선)
      3순위: 전체 평점  (높을수록 우선)

    반환: (선발자 DataFrame, 전체 자격자 DataFrame)
    """
    eligible = [a for a in applicants if a.is_eligible]

    if not eligible:
        return pd.DataFrame(), pd.DataFrame()

    records = []
    for a in eligible:
        records.append(
            {
                # ─ 식별
                "성명": a.name,
                # ─ 학적 (표시용)
                "학년": f"{a.grade}학년" if a.grade > 0 else "미확인",
                "_학년정렬": a.grade,           # 정렬용 숨김 컬럼
                "전공": a.major or "미확인",
                "이수학점": a.completed_credits,
                "졸업기준학점": a.graduation_credits,
                "이수율(%)": round(a.completion_rate * 100, 1),
                "_이수율정렬": a.completion_rate,  # 정렬용 숨김 컬럼
                "GPA": a.gpa,
                # ─ 점수
                "학년점수": a.grade_score,
                "이수율점수": a.completion_score,
                "가산점": a.bonus_score,
                "총점": a.total_score,
                # ─ 가산점 세부
                "이공계/방산": "✓" if a.bonus_stem else "",
                "자격증/어학": "✓" if a.bonus_cert else "",
                "봉사50h+": "✓" if a.bonus_volunteer else "",
                # ─ 서류 제출 현황
                "자립확인서": "✓" if a.is_eligible else "✗",
                "재학증명서": "✓" if a.has_enrollment else "미확인",
                "성적증명서": "✓" if a.has_transcript else "미확인",
                # ─ 처리 메모
                "비고": " | ".join(a.parse_notes) if a.parse_notes else "정상 처리",
            }
        )

    df = pd.DataFrame(records)

    # 정렬: 총점 ↓ → 이수율 ↓ → 학년 ↓ → GPA ↓
    df_sorted = df.sort_values(
        by=["총점", "_이수율정렬", "_학년정렬", "GPA"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    # 순위 부여
    df_sorted.insert(0, "순위", range(1, len(df_sorted) + 1))

    # 정렬용 숨김 컬럼 제거
    df_sorted.drop(columns=["_학년정렬", "_이수율정렬"], inplace=True)

    selected = df_sorted.head(n).copy()

    logger.info(
        f"최종 선발 완료 — 자격자 {len(eligible)}명 중 {len(selected)}명 선발"
    )
    return selected, df_sorted


# ──────────────────────────────────────────────────────────────────────
# 통계 리포트 생성
# ──────────────────────────────────────────────────────────────────────
def build_report(
    selected: pd.DataFrame, all_eligible: pd.DataFrame, total_applicants: int
) -> Dict[str, Any]:
    """선발 결과 기반 통계 딕셔너리 생성"""
    if selected.empty:
        return {}

    sel_n = len(selected)
    stem_n = (selected["이공계/방산"] == "✓").sum()
    cert_n = (selected["자격증/어학"] == "✓").sum()
    vol_n = (selected["봉사50h+"] == "✓").sum()

    return {
        "total_applicants": total_applicants,
        "eligible_count": len(all_eligible),
        "selected_count": sel_n,
        "selection_rate": round(sel_n / total_applicants * 100, 1) if total_applicants else 0,
        "avg_score": round(selected["총점"].mean(), 2),
        "max_score": round(selected["총점"].max(), 2),
        "min_score": round(selected["총점"].min(), 2),
        "grade_dist": selected["학년"].value_counts().to_dict(),
        "stem_count": int(stem_n),
        "stem_rate": round(stem_n / sel_n * 100, 1) if sel_n else 0,
        "cert_count": int(cert_n),
        "vol_count": int(vol_n),
        "avg_gpa": round(selected["GPA"].mean(), 2),
        "avg_completion": round(selected["이수율(%)"].mean(), 1),
    }


# ──────────────────────────────────────────────────────────────────────
# 데모 데이터 생성 (테스트 전용)
# ──────────────────────────────────────────────────────────────────────
def make_demo_applicants(n: int = 20) -> List[ApplicantData]:
    """실제 PDF 없이 기능을 시연하기 위한 더미 데이터 생성"""
    import random

    random.seed(42)

    sample_names = [
        "김민준", "이서연", "박도윤", "최서현", "정예은",
        "강지호", "조수아", "윤민서", "장하은", "임준혁",
        "오지원", "한소율", "신재현", "권나연", "유태양",
        "배수빈", "노현우", "심지유", "문성민", "허다은",
        "서지훈", "안채원", "남기태", "고은서", "류민호",
        "전수현", "양준서", "설아린", "마지현", "제갈민",
    ]
    sample_majors = [
        "컴퓨터공학과", "전자공학과", "기계공학과", "국방학과",
        "경영학과", "사회복지학과", "심리학과", "국어국문학과",
        "소프트웨어학과", "방위산업학과", "화학공학과", "물리학과",
    ]

    results = []
    for i in range(n):
        a = ApplicantData(
            applicant_key=f"demo_{i}",
            name=sample_names[i % len(sample_names)],
            grade=random.randint(1, 4),
            major=sample_majors[random.randint(0, len(sample_majors) - 1)],
            completed_credits=random.uniform(10, 135),
            graduation_credits=random.choice([120.0, 130.0, 140.0]),
            gpa=round(random.uniform(1.5, 4.3), 2),
            has_certificate=random.random() > 0.5,
            volunteer_hours=random.choice([0, 20, 55, 80, 100]),
            is_military=random.random() > 0.6,
            is_eligible=random.random() > 0.1,  # 90% 자격 충족
            has_enrollment=True,
            has_transcript=True,
        )
        ScoringEngine.calculate(a)
        results.append(a)

    return results


# ──────────────────────────────────────────────────────────────────────
# Streamlit UI
# ──────────────────────────────────────────────────────────────────────
def main() -> None:
    # ── 페이지 기본 설정 ──────────────────────────────────────
    st.set_page_config(
        page_title="한영자장학재단 | 장학생 선발 시스템",
        page_icon="🎓",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── 전역 CSS ──────────────────────────────────────────────
    st.markdown(
        """
        <style>
          [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
          .report-box {
            background: #f0f4ff; border-left: 5px solid #1a237e;
            padding: 1.2rem 1.5rem; border-radius: 6px;
            margin: 1rem 0; line-height: 1.8;
          }
          .badge-selected {
            background: #4caf50; color: white; padding: 2px 8px;
            border-radius: 12px; font-size: 0.8rem; font-weight: 700;
          }
          .footer-seal {
            text-align: center; color: #777; font-size: 0.82rem; padding: 1rem 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── 헤더 배너 ─────────────────────────────────────────────
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #0d1b5e, #1a3a8f);
            padding: 1.8rem 2rem; border-radius: 12px;
            margin-bottom: 1.5rem; color: white; text-align: center;
        ">
            <div style="font-size:2.2rem; font-weight:900; letter-spacing:2px;">🎓 한영자장학재단</div>
            <div style="font-size:1.1rem; font-weight:300; margin-top:.4rem; opacity:.9;">
                장학생 자동 선발 시스템 &nbsp;|&nbsp; 후원사: 삼양
            </div>
            <div style="font-size:.85rem; opacity:.7; margin-top:.3rem;">
                수여식: 2026년 4월 30일 &nbsp;·&nbsp;
                이사장: 전동진 &nbsp;·&nbsp; 사무국장: 임재영
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── 사이드바 ──────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## 📌 선발 기준")
        st.markdown(
            """
            | 항목 | 배점 |
            |---|---|
            | 학년 점수 | 최대 50점 |
            | 학업 이수율 | 최대 50점 |
            | 가산점 | 최대 10점 |

            **학년별 점수**
            - 4학년 → 50점
            - 3학년 → 35점
            - 2학년 → 20점
            - 1학년 → 5점

            **가산점 세부**
            - 이공계/방산 전공 → +5
            - 국가자격증/어학 → +3
            - 봉사 50h 이상 → +2
            """
        )
        st.markdown("---")
        st.markdown("## 📁 ZIP 구조 예시")
        st.code(
            "📦 신청서류.zip\n"
            "├── 홍길동/\n"
            "│   ├── 자립지원대상자확인서.pdf\n"
            "│   ├── 재학증명서.pdf\n"
            "│   ├── 성적증명서.pdf\n"
            "│   └── 가산점서류.pdf\n"
            "└── 김철수/ ...",
            language=None,
        )
        st.markdown("---")
        st.markdown(
            "**필수 서류:** 자립지원 대상자 확인서가 없는 신청자는 자동 제외됩니다.",
            help="자립준비청년 지원 자격 검증을 위한 필수 서류입니다.",
        )
        st.markdown("---")
        st.caption(
            "🔒 개인정보보호법 준수\n"
            "주민등록번호 뒷자리 등 민감 정보는\n"
            "추출 즉시 마스킹 처리됩니다."
        )

    # ── 메인 탭 ───────────────────────────────────────────────
    tab_upload, tab_result, tab_report = st.tabs(
        ["📤 서류 업로드", "🏆 선발 결과", "📊 통계 리포트"]
    )

    # ══════════════════════════════════════════════════════════
    # 탭 1: 파일 업로드 & 분석
    # ══════════════════════════════════════════════════════════
    with tab_upload:
        st.subheader("서류 업로드 및 분석")
        st.markdown(
            "신청자별 **4종 서류**(자립지원 대상자 확인서, 재학증명서, "
            "성적증명서, 가산점 서류)가 신청자 폴더별로 정리된 "
            "**ZIP 파일**을 업로드하세요."
        )

        uploaded = st.file_uploader("ZIP 파일 선택", type=["zip"])

        col_btn, col_demo = st.columns([2, 3])
        with col_btn:
            run_btn = st.button(
                "🔍 분석 시작",
                type="primary",
                disabled=(uploaded is None),
                use_container_width=True,
            )
        with col_demo:
            demo_btn = st.button(
                "🧪 데모 데이터로 테스트 (PDF 없이 시연)",
                use_container_width=True,
            )

        # ── 데모 모드 ─────────────────────────────────────────
        if demo_btn:
            with st.spinner("데모 데이터 생성 중..."):
                _log_buffer.truncate(0)
                _log_buffer.seek(0)
                demo_applics = make_demo_applicants(30)
                sel_df, all_df = select_scholars(demo_applics, MAX_SCHOLARS)
                st.session_state.update(
                    {
                        "selected_df": sel_df,
                        "all_df": all_df,
                        "applicants": demo_applics,
                        "log": _log_buffer.getvalue(),
                        "is_demo": True,
                    }
                )
            st.success(
                f"✅ 데모 완료! 총 {len(demo_applics)}명 중 **{len(sel_df)}명** 선발"
            )

        # ── 실제 ZIP 분석 ─────────────────────────────────────
        if run_btn and uploaded:
            _log_buffer.truncate(0)
            _log_buffer.seek(0)

            progress = st.progress(0, text="ZIP 파일 압축 해제 중...")

            try:
                zip_bytes = uploaded.read()

                # ZIP 유효성 사전 검사
                if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
                    st.error("❌ 유효하지 않은 ZIP 파일입니다.")
                    st.stop()

                progress.progress(15, text="PDF 파싱 중...")
                processor = DocumentProcessor()
                applics = processor.process(zip_bytes)

                progress.progress(70, text="점수 계산 및 선발 처리 중...")

                if not applics:
                    st.error(
                        "❌ ZIP 파일에서 신청자 데이터를 찾을 수 없습니다. "
                        "파일 구조를 확인해 주세요."
                    )
                    st.stop()

                sel_df, all_df = select_scholars(applics, MAX_SCHOLARS)

                progress.progress(95, text="결과 저장 중...")
                st.session_state.update(
                    {
                        "selected_df": sel_df,
                        "all_df": all_df,
                        "applicants": applics,
                        "log": _log_buffer.getvalue(),
                        "is_demo": False,
                    }
                )
                progress.progress(100, text="완료!")

                st.success(
                    f"🎉 분석 완료! 총 **{len(applics)}명** 신청자 중 "
                    f"**{len(sel_df)}명** 최종 선발"
                )

            except zipfile.BadZipFile:
                st.error("❌ ZIP 파일이 손상되었거나 형식이 올바르지 않습니다.")
            except MemoryError:
                st.error("❌ 파일이 너무 큽니다. 더 작은 파일로 분할 후 업로드하세요.")
            except Exception as exc:
                st.error(f"❌ 처리 중 오류 발생: {exc}")
                logger.error(f"처리 오류: {exc}", exc_info=True)

        # ── 처리 로그 (투명성 원칙) ───────────────────────────
        if "log" in st.session_state and st.session_state["log"]:
            with st.expander("📋 처리 로그 보기 — 투명성 원칙에 따른 처리 이력", expanded=False):
                st.code(st.session_state["log"], language=None)

        # ── 파싱 경고사항 표시 ────────────────────────────────
        if "applicants" in st.session_state:
            warnings = [
                {"성명": a.name, "주의사항": " | ".join(a.parse_notes)}
                for a in st.session_state["applicants"]
                if a.parse_notes
            ]
            if warnings:
                with st.expander(f"⚠️ 파싱 주의사항 ({len(warnings)}건)", expanded=False):
                    st.dataframe(pd.DataFrame(warnings), use_container_width=True)

    # ══════════════════════════════════════════════════════════
    # 탭 2: 선발 결과
    # ══════════════════════════════════════════════════════════
    with tab_result:
        st.subheader("최종 선발 결과")

        if "selected_df" not in st.session_state:
            st.info("📤 '서류 업로드' 탭에서 파일을 업로드하고 분석을 먼저 실행하세요.")
            st.stop()

        sel_df: pd.DataFrame = st.session_state["selected_df"]

        if sel_df.empty:
            st.warning("⚠️ 자격 요건(자립지원 대상자 확인서)을 충족한 신청자가 없습니다.")
            st.stop()

        is_demo = st.session_state.get("is_demo", False)

        # ── 선발 공고 헤더 ────────────────────────────────────
        st.markdown(
            f"""
            <div style="
                background:#e8f5e9; border-left:5px solid #2e7d32;
                padding:1rem 1.5rem; border-radius:6px; margin-bottom:1rem;
            ">
                <strong>🏆 2026년도 한영자장학재단 장학생 최종 선발 명단</strong>
                {'&nbsp;<span class="badge-selected">데모</span>' if is_demo else ""}<br>
                <span style="color:#555; font-size:.88rem;">
                    선발 기준일: {datetime.now().strftime("%Y년 %m월 %d일")} &nbsp;|&nbsp;
                    수여식: 2026년 4월 30일 &nbsp;|&nbsp;
                    이사장 전동진 印 &nbsp;|&nbsp; 사무국장 임재영 印
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # ── 표시 컬럼 설정 ────────────────────────────────────
        display_cols = [
            "순위", "성명", "학년", "전공",
            "이수학점", "졸업기준학점", "이수율(%)", "GPA",
            "학년점수", "이수율점수", "가산점", "총점",
            "이공계/방산", "자격증/어학", "봉사50h+",
        ]
        show_df = sel_df[display_cols].copy()

        # ── 상위 3위 하이라이트 ───────────────────────────────
        RANK_COLORS = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}

        def _highlight_rank(row: pd.Series) -> List[str]:
            color = RANK_COLORS.get(int(row["순위"]), "")
            style = f"background-color:{color}; font-weight:bold" if color else ""
            return [style] * len(row)

        styled = show_df.style.apply(_highlight_rank, axis=1).format(
            {
                "이수학점": "{:.1f}",
                "졸업기준학점": "{:.0f}",
                "이수율(%)": "{:.1f}",
                "GPA": "{:.2f}",
                "학년점수": "{:.0f}",
                "이수율점수": "{:.2f}",
                "가산점": "{:.0f}",
                "총점": "{:.2f}",
            }
        )

        st.dataframe(styled, use_container_width=True, height=600)

        # ── 다운로드 버튼 ─────────────────────────────────────
        st.markdown("---")
        c1, c2 = st.columns(2)

        with c1:
            csv_sel = sel_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                label="📥 선발 명단 CSV 다운로드",
                data=csv_sel,
                file_name=f"한영자장학재단_선발명단_{datetime.now():%Y%m%d}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with c2:
            all_df = st.session_state.get("all_df", pd.DataFrame())
            if not all_df.empty:
                csv_all = all_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="📥 전체 자격자 명단 CSV 다운로드",
                    data=csv_all,
                    file_name=f"한영자장학재단_전체명단_{datetime.now():%Y%m%d}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

    # ══════════════════════════════════════════════════════════
    # 탭 3: 통계 리포트
    # ══════════════════════════════════════════════════════════
    with tab_report:
        st.subheader("선발 통계 리포트")

        if "selected_df" not in st.session_state:
            st.info("📤 '서류 업로드' 탭에서 파일을 업로드하고 분석을 먼저 실행하세요.")
            st.stop()

        sel_df = st.session_state["selected_df"]
        all_df = st.session_state.get("all_df", pd.DataFrame())
        all_applics = st.session_state.get("applicants", [])

        if sel_df.empty:
            st.warning("통계를 표시할 선발 데이터가 없습니다.")
            st.stop()

        rpt = build_report(sel_df, all_df, len(all_applics))

        # ── 핵심 지표 카드 ────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("총 신청자", f"{rpt['total_applicants']}명")
        c2.metric("자격 충족", f"{rpt['eligible_count']}명")
        c3.metric("최종 선발", f"{rpt['selected_count']}명")
        c4.metric("선발률", f"{rpt['selection_rate']}%")
        c5.metric("평균 점수", f"{rpt['avg_score']}점")

        st.markdown("---")

        # ── 학년별 현황 & 점수 분포 ───────────────────────────
        col_l, col_r = st.columns(2)

        with col_l:
            st.markdown("#### 학년별 선발 인원")
            grade_df = (
                pd.DataFrame.from_dict(
                    rpt["grade_dist"], orient="index", columns=["인원"]
                )
                .sort_index(ascending=False)
            )
            st.bar_chart(grade_df, color="#1a3a8f")

        with col_r:
            st.markdown("#### 선발자 점수 분포")
            score_df = sel_df[["성명", "총점"]].set_index("성명")
            st.bar_chart(score_df, color="#2e7d32")

        st.markdown("---")

        # ── 가산점 현황 ───────────────────────────────────────
        st.markdown("#### 가산점 취득 현황 (선발자 기준)")
        a1, a2, a3 = st.columns(3)
        a1.metric(
            "이공계/방산 전공자",
            f"{rpt['stem_count']}명",
            f"선발자 대비 {rpt['stem_rate']}%",
        )
        a2.metric("자격증/어학 성적 보유", f"{rpt['cert_count']}명")
        a3.metric("봉사활동 50h 이상", f"{rpt['vol_count']}명")

        st.markdown("---")

        # ── 선발 취지 보고서 ──────────────────────────────────
        st.markdown("#### 📝 선발 취지 보고서")
        st.markdown(
            f"""
            <div class="report-box">
            <strong>한영자장학재단 2026년도 장학생 선발 결과 보고</strong><br><br>

            본 재단은 <strong>자립준비청년의 실질적 자립 지원</strong>을 목적으로,
            대학 졸업을 앞둔 자립지원 대상자 <strong>{rpt['total_applicants']}명</strong>의
            지원서를 심사하였습니다.<br><br>

            객관적 지표(학년 점수, 학업 이수율)와 사회적 역량(이공계 전공, 자격증, 봉사)을
            종합하여 <strong>{rpt['selected_count']}명</strong>을 최종 선발하였으며,
            선발자의 평균 점수는 <strong>{rpt['avg_score']}점</strong>
            (최고 {rpt['max_score']}점 / 최저 {rpt['min_score']}점),
            평균 이수율은 <strong>{rpt['avg_completion']}%</strong>입니다.<br><br>

            후원사 <strong>삼양</strong>의 방산기업 특성을 반영하여
            이공계·방산 관련 전공자 <strong>{rpt['stem_count']}명 ({rpt['stem_rate']}%)</strong>에게
            가산점이 부여되었으며, 자격증·어학 성적 보유자 {rpt['cert_count']}명,
            봉사활동 50시간 이상 이행자 {rpt['vol_count']}명이 추가 가산점을 받았습니다.<br><br>

            모든 선발 과정은 자동화된 알고리즘에 의해 투명하게 처리되었으며,
            처리 로그가 기록·보존됩니다.
            장학금 수여식은 <strong>2026년 4월 30일</strong>에 진행될 예정입니다.<br><br>

            <em>이사장 전동진 &nbsp;印 &nbsp;&nbsp; 사무국장 임재영 &nbsp;印</em>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── 푸터 ──────────────────────────────────────────────────
    st.markdown(
        """
        <div class="footer-seal">
            한영자장학재단 장학생 선발 시스템 &nbsp;|&nbsp;
            이사장 전동진 印 &nbsp;·&nbsp; 사무국장 임재영 印<br>
            본 시스템은 「개인정보보호법」에 따라 주민등록번호 등 민감 정보를 마스킹 처리합니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
