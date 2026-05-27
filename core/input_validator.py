"""
core/input_validator.py
------------------------
Phân tích chất lượng requirement đầu vào TRƯỚC khi gọi LLM.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class IssueSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class ValidationIssue:
    severity: IssueSeverity
    code: str
    title: str
    description: str
    suggestion: str
    example: str = ""


@dataclass
class ValidationResult:
    is_valid: bool
    can_generate: bool
    quality_score: int
    quality_label: str
    quality_color: str
    issues: list[ValidationIssue] = field(default_factory=list)
    detected_features: list[str] = field(default_factory=list)
    detected_criteria_count: int = 0
    estimated_tc_count: str = ""
    summary: str = ""

    @property
    def critical_issues(self):
        return [i for i in self.issues if i.severity == IssueSeverity.CRITICAL]

    @property
    def warning_issues(self):
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]

    @property
    def info_issues(self):
        return [i for i in self.issues if i.severity == IssueSeverity.INFO]


# ── Regex ──────────────────────────────────────────────────────────────────

_US_ACTOR = re.compile(
    r"\bas a\b"
    r"|\blà người dùng\b|\blà (một )?người\b|\bvới tư cách\b"
    r"|\bnhư là (một )?(người|khách|admin|quản trị)\b",
    re.IGNORECASE,
)
_US_GOAL = re.compile(
    r"\bi want\b|\bwe want\b|\buser wants\b"
    r"|\btôi muốn\b|\bchúng tôi muốn\b|\bngười dùng muốn\b"
    r"|\bmuốn (được |có thể |nhận |xem |thực hiện )\b",
    re.IGNORECASE,
)
_US_BENEFIT = re.compile(
    r"\bso that\b|\bin order to\b"
    r"|\bđể biết\b|\bđể có thể\b|\bđể (tôi|người dùng|khách hàng)\b"
    r"|\bnhằm\b|\bđể\b(?=.{0,80}(có thể|biết|tránh|giúp|theo dõi|kiểm tra))",
    re.IGNORECASE,
)
_AC_HEADER = re.compile(
    r"\bacceptance criteria\b|\bAC\b|\bcriteria\b|\bgiven\b.*\bwhen\b|\bshould\b",
    re.IGNORECASE,
)
_AC_ITEM = re.compile(r"(?:^|\n)\s*[-•*\d]+[\.\)]\s+\S", re.MULTILINE)

_UC_ACTOR = re.compile(r"\bactor\b|\bprimary actor\b|\buser\b", re.IGNORECASE)
_UC_PRECOND = re.compile(r"\bprecondition\b|\bpre-condition\b", re.IGNORECASE)
_UC_MAINFLOW = re.compile(
    r"\bmain flow\b|\bbasic flow\b|\bnormal flow\b|\bmain path\b"
    r"|\bacceptance criteria\b"  # User Story AC cũng là main flow
    r"|\bi want to\b",  # goal = implicit main flow
    re.IGNORECASE,
)

_UC_ALTFLOW = re.compile(
    r"\balternate flow\b|\balternative\b|\bexception\b|\berror flow\b"
    r"|\bhết hàng\b|\bsai\b|\btrống\b|\bkhông hợp lệ\b"  # Vietnamese negative conditions
    r"|\binvalid\b|\berror\b|\bfail\b|\bnot found\b"
    r"|\bchưa đăng nhập\b|\bchưa có\b",
    re.IGNORECASE,
)

_ACTION_VERBS = re.compile(
    r"\b(?:log in|login|register|sign up|create|update|delete|search|filter|"
    r"upload|download|submit|approve|reject|cancel|pay|checkout|view|navigate|"
    r"click|enter|select|add|remove|edit|save|export|import|generate|send|receive)\b",
    re.IGNORECASE,
)
_EXPECTED_OUTCOMES = re.compile(
    r"\b(?:should|must|shall|expected|result|outcome|display|show|redirect|"
    r"return|error|success|fail|confirm|notify|alert|validate|allow|deny|block)\b",
    re.IGNORECASE,
)
_VAGUE_WORDS = re.compile(
    r"\b(?:etc|something|somehow|appropriate|properly|correctly|normally|"
    r"usual|typical|standard|maybe|might|could|possibly|various|several|many|some)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_WORDS = re.compile(
    r"\b(?:lorem ipsum|todo|tbd|wip|sample text|your text here|xxx|aaa|bbb|test123)\b"
    r"|\bplaceholder\b(?!\s+(?:hiển thị|text|gợi ý|của|cho|là|:))",
    re.IGNORECASE,
)
_FEATURE_SEPARATORS = re.compile(
    r"(?:^|\n)\s*(?:story\s*\d+|feature\s*\d+|use case\s*\d+|UC-\d+|US-\d+|#\s*\d+|\d+\.\s+[A-Z])",
    re.IGNORECASE | re.MULTILINE,
)
_DATA_FIELDS = re.compile(
    r"\b(?:email|password|username|name|phone|address|date|amount|price|"
    r"quantity|id|code|status|type|category|role|permission)\b",
    re.IGNORECASE,
)
_AUTH_MENTIONS = re.compile(
    r"\b(?:login|authenticate|authorize|permission|role|admin|user|access|"
    r"token|session|secure|protect|restrict|only.*can|cannot|not allowed)\b",
    re.IGNORECASE,
)


# ── Per-type validators ─────────────────────────────────────────────────────


def _validate_user_story(text: str, issues: list) -> dict:
    meta = {
        "has_actor": bool(_US_ACTOR.search(text)),
        "has_goal": bool(_US_GOAL.search(text)),
        "has_benefit": bool(_US_BENEFIT.search(text)),
        "has_ac": bool(_AC_HEADER.search(text)),
        "ac_item_count": len(_AC_ITEM.findall(text)),
        "story_count": max(1, len(_FEATURE_SEPARATORS.findall(text))),
    }
    if not meta["has_actor"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "US_MISSING_ACTOR",
                "Chưa xác định ai đang sử dụng tính năng này",
                "Cần ghi rõ người dùng là ai (khách vãng lai, khách đã đăng nhập, admin...). Nếu không có thông tin này, AI sẽ không biết cần kiểm tra quyền hạn gì.",
                "Thêm 'As a [vai trò]' vào đầu mỗi story. Ví dụ: 'As a khách hàng chưa đăng nhập' hoặc 'As a admin'.",
                "As a khách hàng đã đăng nhập, I want to xem lịch sử đơn hàng...",
            )
        )
    if not meta["has_goal"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "US_MISSING_GOAL",
                "Chưa mô tả người dùng muốn làm gì",
                "Cần ghi rõ hành động người dùng muốn thực hiện. Không có phần này, AI không biết tính năng cần test là gì.",
                "Thêm 'I want to [hành động cụ thể]'. Ví dụ: đăng nhập, đặt hàng, xem danh sách sản phẩm...",
                "As a khách hàng, I want to thêm sản phẩm vào giỏ hàng...",
            )
        )
    if not meta["has_ac"] and meta["ac_item_count"] == 0:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "US_MISSING_AC",
                "Chưa có tiêu chí kiểm tra (Acceptance Criteria)",
                "Acceptance Criteria là danh sách các điều kiện cụ thể cần đạt được. Không có phần này, AI chỉ sinh được test cases rất chung chung, dễ bỏ sót các trường hợp quan trọng.",
                "Thêm mục 'Acceptance Criteria:' và liệt kê từng điều kiện. Nghĩ đến: trường nào bắt buộc? Nhập sai thì hiện thông báo gì? Thao tác xong thì chuyển đến đâu?",
                "Acceptance Criteria:\n- Trường Email và Mật khẩu là bắt buộc\n- Nhập sai thông tin → hiện thông báo 'Email hoặc mật khẩu không đúng'\n- Sai 5 lần liên tiếp → khoá tài khoản 30 phút",
            )
        )
    elif meta["ac_item_count"] < 3 and meta["story_count"] == 1:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "US_FEW_AC",
                f"Chỉ có {meta['ac_item_count']} tiêu chí kiểm tra — nên bổ sung thêm",
                "Ít tiêu chí đồng nghĩa với ít test cases được sinh ra. Các trường hợp lỗi, giới hạn giá trị, phân quyền thường bị bỏ sót.",
                "Bổ sung thêm tiêu chí bằng cách tự hỏi: Trường nào là bắt buộc? Nếu để trống thì sao? Có giới hạn ký tự không? Ai được phép làm việc này? Nếu thất bại thì hiện thông báo gì?",
                "",
            )
        )
    if not meta["has_benefit"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.INFO,
                "US_MISSING_BENEFIT",
                "Chưa giải thích tại sao người dùng cần tính năng này",
                "Phần 'So that...' giúp AI hiểu mục đích thật sự của tính năng, từ đó sinh thêm được các test case kiểm tra đúng giá trị business.",
                "Thêm 'So that [lý do/lợi ích]'. Ví dụ: 'so that tôi có thể theo dõi tình trạng đơn hàng của mình'.",
                "...So that tôi không cần gọi điện hỏi nhân viên về tình trạng đơn hàng.",
            )
        )
    return meta


def _validate_use_case(text: str, issues: list) -> dict:
    meta = {
        "has_actor": bool(_UC_ACTOR.search(text)),
        "has_precond": bool(_UC_PRECOND.search(text)),
        "has_main_flow": bool(_UC_MAINFLOW.search(text)),
        "has_alt_flow": bool(_UC_ALTFLOW.search(text)),
        "uc_count": max(1, len(_FEATURE_SEPARATORS.findall(text))),
    }
    if not meta["has_actor"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "UC_MISSING_ACTOR",
                "Chưa xác định ai thực hiện use case này",
                "Cần ghi rõ người dùng là ai. Nếu không có, AI sẽ không biết cần kiểm tra quyền truy cập như thế nào.",
                "Thêm dòng 'Actor: [vai trò]'. Ví dụ: Actor: Khách hàng đã đăng nhập, Actor: Quản trị viên...",
                "Actor: Khách hàng đã đăng nhập\nSecondary Actor: Hệ thống gửi email",
            )
        )
    if not meta["has_main_flow"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "UC_MISSING_MAIN_FLOW",
                "Chưa mô tả luồng thực hiện chính",
                "Cần mô tả từng bước người dùng thực hiện khi mọi thứ diễn ra bình thường. Đây là phần quan trọng nhất để AI sinh được test cases cho happy path.",
                "Thêm mục 'Main Flow:' và liệt kê các bước theo thứ tự. Mỗi bước ghi rõ: người dùng làm gì → hệ thống phản hồi gì.",
                "Main Flow:\n1. Người dùng truy cập trang /login\n2. Nhập email và mật khẩu\n3. Hệ thống kiểm tra thông tin\n4. Hệ thống chuyển hướng về trang chủ",
            )
        )
    if not meta["has_alt_flow"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "UC_MISSING_ALT_FLOW",
                "Chưa mô tả các trường hợp thất bại hoặc ngoại lệ",
                "Cần mô tả những gì xảy ra khi có lỗi hoặc điều kiện bất thường. Không có phần này, AI sẽ sinh ít test cases cho trường hợp lỗi.",
                "Thêm mục 'Exception Flow:' và mô tả các tình huống như: nhập sai thông tin, hết hàng, chưa đăng nhập, mất kết nối...",
                "Exception Flow:\n- Nhập sai mật khẩu → hiện thông báo lỗi, không chuyển trang\n- Tài khoản bị khoá → hiện hướng dẫn liên hệ hỗ trợ",
            )
        )
    if not meta["has_precond"]:
        issues.append(
            ValidationIssue(
                IssueSeverity.INFO,
                "UC_MISSING_PRECOND",
                "Chưa ghi điều kiện cần có trước khi thực hiện",
                "Preconditions là những điều kiện phải đúng trước khi bắt đầu use case. Ví dụ: người dùng đã đăng nhập, sản phẩm còn hàng... Không có phần này, AI phải tự đoán.",
                "Thêm mục 'Preconditions:' và liệt kê các điều kiện tiên quyết.",
                "Preconditions:\n- Người dùng đã đăng nhập\n- Giỏ hàng có ít nhất 1 sản phẩm\n- Hệ thống thanh toán đang hoạt động",
            )
        )
    return meta


def _validate_natural_language(text: str, issues: list) -> dict:
    meta = {
        "action_count": len(_ACTION_VERBS.findall(text)),
        "outcome_count": len(_EXPECTED_OUTCOMES.findall(text)),
        "vague_count": len(_VAGUE_WORDS.findall(text)),
        "feature_count": max(1, len(_FEATURE_SEPARATORS.findall(text))),
    }
    if meta["action_count"] < 2:
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "NL_NO_ACTIONS",
                "Chưa mô tả người dùng làm gì cụ thể",
                "Requirement cần nêu rõ các hành động: người dùng nhấn gì, nhập gì, chọn gì. Nếu chỉ mô tả chung chung, AI sẽ không biết cần tạo test case cho hành động nào.",
                "Mô tả cụ thể từng hành động. Ví dụ: 'Người dùng nhập email và mật khẩu rồi nhấn Đăng nhập', 'Admin chọn sản phẩm và nhấn Xoá'.",
                "Người dùng nhập từ khoá vào ô tìm kiếm và nhấn Enter. Hệ thống hiển thị danh sách sản phẩm khớp với từ khoá.",
            )
        )
    if meta["outcome_count"] < 2:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "NL_NO_OUTCOMES",
                "Chưa mô tả kết quả mong đợi sau mỗi hành động",
                "Cần ghi rõ sau khi người dùng làm gì đó thì hệ thống phản hồi như thế nào. Không có phần này, AI sẽ tự đoán kết quả và có thể sinh test cases không đúng với thực tế.",
                "Với mỗi hành động, thêm kết quả tương ứng. Ví dụ: 'Đăng nhập thành công → chuyển về trang chủ, hiện tên người dùng trên header'. 'Nhập sai mật khẩu → hiện thông báo đỏ bên dưới ô nhập'.",
                "Nhấn 'Đặt hàng' → hệ thống gửi email xác nhận và hiển thị trang cảm ơn với mã đơn hàng.",
            )
        )
    if meta["vague_count"] > 5:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "NL_TOO_VAGUE",
                f"Có {meta['vague_count']} cụm từ mơ hồ, khó kiểm tra",
                "Các cụm như 'hiển thị đúng', 'hoạt động bình thường', 'xử lý phù hợp' không đủ cụ thể để tạo test case. AI sẽ không biết 'đúng' nghĩa là gì trong ngữ cảnh này.",
                "Thay các cụm mơ hồ bằng mô tả cụ thể và có thể đo lường được. Ví dụ: thay 'hiển thị đúng' → 'hiển thị thông báo Đặt hàng thành công màu xanh lá ở góc trên phải'.",
                "Thay 'validate đúng định dạng' → 'kiểm tra email có chứa @ và tên miền hợp lệ, tối đa 255 ký tự'.",
            )
        )
    return meta


def _validate_common(text: str, input_type: str, issues: list) -> dict:
    placeholder_matches = _PLACEHOLDER_WORDS.findall(text)
    meta = {
        "word_count": len(text.split()),
        "char_count": len(text.strip()),
        "has_placeholder": bool(placeholder_matches),
        "data_field_count": len(set(_DATA_FIELDS.findall(text.lower()))),
        "has_auth": bool(_AUTH_MENTIONS.search(text)),
        "feature_count": max(1, len(_FEATURE_SEPARATORS.findall(text))),
        "line_count": len([l for l in text.splitlines() if l.strip()]),
    }
    if meta["word_count"] < 20:
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "TOO_SHORT",
                "Requirement quá ngắn, AI không đủ thông tin để sinh test cases",
                f"Hiện tại chỉ có {meta['word_count']} từ. Để sinh được test cases có giá trị, cần mô tả rõ hơn về tính năng, người dùng, điều kiện và kết quả mong đợi.",
                "Hãy bổ sung: tính năng này làm gì? Ai sử dụng? Người dùng thao tác như thế nào? Kết quả mong đợi là gì? Nếu xảy ra lỗi thì hiển thị gì?",
                "",
            )
        )
    elif meta["word_count"] < 50:
        issues.append(
            ValidationIssue(
                IssueSeverity.WARNING,
                "SHORT_REQUIREMENT",
                f"Requirement còn khá ngắn ({meta['word_count']} từ)",
                "Requirement ngắn thường bỏ sót các trường hợp lỗi, giới hạn giá trị và phân quyền. AI sẽ sinh được ít test cases hơn thực tế cần.",
                "Hãy bổ sung thêm: trường nào bắt buộc/không bắt buộc? Có giới hạn ký tự không? Thông báo lỗi hiển thị chính xác là gì? Ai được phép thực hiện thao tác này?",
                "",
            )
        )
    if meta["has_placeholder"]:
        unique_matches = list(dict.fromkeys(m.strip() for m in placeholder_matches))
        found_str = ", ".join(f"'{m}'" for m in unique_matches[:5])
        issues.append(
            ValidationIssue(
                IssueSeverity.CRITICAL,
                "HAS_PLACEHOLDER",
                "Requirement còn chứa nội dung chưa điền",
                f"Phát hiện {len(unique_matches)} chỗ chưa điền: {found_str}. AI sẽ sinh test cases dựa trên nội dung này và cho kết quả sai.",
                f"Tìm và thay thế các từ sau bằng nội dung thực tế: {found_str}.",
                "",
            )
        )
    if meta["data_field_count"] > 0 and meta["word_count"] < 100:
        issues.append(
            ValidationIssue(
                IssueSeverity.INFO,
                "MISSING_VALIDATION_RULES",
                "Có nhắc đến các trường dữ liệu nhưng chưa nêu quy tắc nhập liệu",
                f"Phát hiện {meta['data_field_count']} trường dữ liệu (email, mật khẩu, số điện thoại...) nhưng chưa thấy quy tắc validate. AI sẽ không sinh được test cases kiểm tra giới hạn và định dạng.",
                "Bổ sung quy tắc cho từng trường: độ dài tối thiểu/tối đa, định dạng (email, số điện thoại), bắt buộc hay không, có được trùng không.",
                "Ví dụ: Mật khẩu tối thiểu 8 ký tự, phải có ít nhất 1 chữ hoa và 1 số. Email đúng định dạng, tối đa 255 ký tự, không được trùng trong hệ thống.",
            )
        )
    if meta["has_auth"] and not re.search(
        r"\b(admin|manager|user|guest|member|role)\b", text, re.IGNORECASE
    ):
        issues.append(
            ValidationIssue(
                IssueSeverity.INFO,
                "VAGUE_AUTH",
                "Có nhắc đến đăng nhập/phân quyền nhưng chưa rõ ai được làm gì",
                "Requirement đề cập đến xác thực hoặc phân quyền nhưng chưa liệt kê các vai trò cụ thể. AI sẽ không sinh được test cases kiểm tra đúng người dùng sai role bị chặn.",
                "Liệt kê rõ từng vai trò và quyền hạn tương ứng. Ví dụ: Admin thì được làm gì, khách chưa đăng nhập thì bị chặn ở đâu, người dùng thường thì chỉ xem được gì.",
                "Ví dụ: Chỉ admin mới xoá được tài khoản. Khách chưa đăng nhập không vào được trang /wishlist, sẽ bị chuyển về trang đăng nhập.",
            )
        )
    return meta


def _detect_features(text: str) -> list[str]:
    features = []
    seen = set()

    # Chỉ lấy các dòng "Chức năng X" — đây là feature chính
    titled = re.findall(
        r"(?:^|\n)\s*Chức năng\s+([^\n]{2,50})",
        text,
        re.IGNORECASE,
    )
    for name in titled:
        name = name.strip().rstrip("_").strip()
        if name and name not in seen:
            seen.add(name)
            features.append(name)

    # Fallback nếu không có "Chức năng"
    if not features:
        goals = re.findall(r"i want to ([^.!?\n]{5,50})", text, re.IGNORECASE)
        for g in goals:
            g = g.strip()
            if g and g not in seen:
                seen.add(g)
                features.append(g)

    return features[:20]


def _estimate_tc_count(text: str, input_type: str) -> tuple[int, int]:
    criteria_count = len(_AC_ITEM.findall(text))
    feature_count = max(1, len(_FEATURE_SEPARATORS.findall(text)))
    data_fields = len(set(_DATA_FIELDS.findall(text.lower())))
    has_auth = bool(_AUTH_MENTIONS.search(text))
    word_count = len(text.split())
    base = max(criteria_count, feature_count * 3)
    boundary_tcs = data_fields * 2
    security_tcs = min(data_fields * 2, 10)
    auth_tcs = 3 if has_auth else 0
    total_min = base + boundary_tcs // 2 + auth_tcs
    total_max = base + boundary_tcs + security_tcs + auth_tcs + feature_count * 2
    if word_count > 300:
        total_min = int(total_min * 1.5)
        total_max = int(total_max * 1.5)
    return max(5, total_min), max(total_min + 5, total_max)


def _compute_quality(issues: list, text: str) -> tuple[int, str, str]:
    critical_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
    warning_count = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
    word_count = len(text.split())
    criteria_count = len(_AC_ITEM.findall(text))
    score = 100
    score -= critical_count * 30
    score -= warning_count * 10
    if word_count > 100:
        score += 5
    if word_count > 200:
        score += 5
    if criteria_count >= 5:
        score += 5
    if criteria_count >= 10:
        score += 5
    score = max(0, min(100, score))
    if score >= 85:
        return score, "Excellent", "#22c55e"
    if score >= 70:
        return score, "Good", "#84cc16"
    if score >= 50:
        return score, "Fair", "#f59e0b"
    if score >= 25:
        return score, "Poor", "#f97316"
    return score, "Insufficient", "#ef4444"


def validate_input(
    requirement: str, input_type: str = "User Story"
) -> ValidationResult:
    text = requirement.strip()
    issues: list[ValidationIssue] = []
    common_meta = _validate_common(text, input_type, issues)
    if common_meta["word_count"] < 10:
        score, label, color = _compute_quality(issues, text)
        return ValidationResult(
            is_valid=False,
            can_generate=False,
            quality_score=score,
            quality_label=label,
            quality_color=color,
            issues=issues,
            detected_features=[],
            detected_criteria_count=0,
            estimated_tc_count="N/A",
            summary="Requirement quá ngắn để phân tích.",
        )
    if input_type == "User Story":
        _validate_user_story(text, issues)
    elif input_type == "Use Case Spec":
        _validate_use_case(text, issues)
    else:
        _validate_natural_language(text, issues)
    features = _detect_features(text)
    criteria_count = len(_AC_ITEM.findall(text))
    tc_min, tc_max = _estimate_tc_count(text, input_type)
    score, label, color = _compute_quality(issues, text)
    has_critical = any(i.severity == IssueSeverity.CRITICAL for i in issues)
    can_generate = not has_critical and common_meta["word_count"] >= 10
    crit_n = len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
    warn_n = len([i for i in issues if i.severity == IssueSeverity.WARNING])
    if has_critical:
        summary = f"⛔ Requirement có {crit_n} vấn đề nghiêm trọng cần sửa trước khi generate."
    elif warn_n:
        summary = f"⚠️ Requirement có thể generate nhưng có {warn_n} cảnh báo ảnh hưởng chất lượng TC."
    else:
        summary = (
            f"✅ Requirement chất lượng tốt. Ước lượng ~{tc_min}-{tc_max} test cases."
        )
    return ValidationResult(
        is_valid=not has_critical,
        can_generate=can_generate,
        quality_score=score,
        quality_label=label,
        quality_color=color,
        issues=issues,
        detected_features=features,
        detected_criteria_count=criteria_count,
        estimated_tc_count=f"~{tc_min}-{tc_max} TCs",
        summary=summary,
    )
