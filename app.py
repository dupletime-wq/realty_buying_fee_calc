from __future__ import annotations

import csv
import io
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any


WON = Decimal("1")
EOK = Decimal("100000000")


@dataclass(frozen=True)
class RateBand:
    min_amount: int
    max_amount: int | None
    rate: Decimal
    label: str
    cap: int | None = None


@dataclass(frozen=True)
class StampBand:
    min_exclusive: int
    max_inclusive: int | None
    tax: int
    label: str


@dataclass(frozen=True)
class PurchaseInputs:
    purchase_price: int
    tax_base: int
    bond_standard_value: int
    over_85m2: bool
    buyer_type: str
    home_count_after: str
    regulated_area: bool
    temporary_two_home: bool
    brokerage_rate: Decimal
    brokerage_vat_rate: Decimal
    bond_discount_rate: Decimal
    acquisition_tax_relief: int
    relief_related_extra_tax: int
    sale_stamp_buyer_share: Decimal
    legal_service_fee: int
    ownership_registration_fee: int
    other_transaction_fee: int
    loan_enabled: bool
    loan_amount: int
    collateral_ratio: Decimal
    loan_stamp_buyer_share: Decimal
    mortgage_registration_fee: int
    loan_other_fee: int


SEOUL_HOME_BROKERAGE_BANDS = [
    RateBand(0, 50_000_000, Decimal("0.006"), "5천만원 미만", 250_000),
    RateBand(50_000_000, 200_000_000, Decimal("0.005"), "5천만원 이상 2억원 미만", 800_000),
    RateBand(200_000_000, 900_000_000, Decimal("0.004"), "2억원 이상 9억원 미만"),
    RateBand(900_000_000, 1_200_000_000, Decimal("0.005"), "9억원 이상 12억원 미만"),
    RateBand(1_200_000_000, 1_500_000_000, Decimal("0.006"), "12억원 이상 15억원 미만"),
    RateBand(1_500_000_000, None, Decimal("0.007"), "15억원 이상"),
]

STAMP_TAX_BANDS = [
    StampBand(10_000_000, 30_000_000, 20_000, "1천만원 초과 3천만원 이하"),
    StampBand(30_000_000, 50_000_000, 40_000, "3천만원 초과 5천만원 이하"),
    StampBand(50_000_000, 100_000_000, 70_000, "5천만원 초과 1억원 이하"),
    StampBand(100_000_000, 1_000_000_000, 150_000, "1억원 초과 10억원 이하"),
    StampBand(1_000_000_000, None, 350_000, "10억원 초과"),
]

SEOUL_HOME_BOND_BANDS = [
    RateBand(0, 20_000_000, Decimal("0"), "2천만원 미만"),
    RateBand(20_000_000, 50_000_000, Decimal("0.013"), "2천만원 이상 5천만원 미만"),
    RateBand(50_000_000, 100_000_000, Decimal("0.019"), "5천만원 이상 1억원 미만"),
    RateBand(100_000_000, 160_000_000, Decimal("0.021"), "1억원 이상 1억6천만원 미만"),
    RateBand(160_000_000, 260_000_000, Decimal("0.023"), "1억6천만원 이상 2억6천만원 미만"),
    RateBand(260_000_000, 600_000_000, Decimal("0.026"), "2억6천만원 이상 6억원 미만"),
    RateBand(600_000_000, None, Decimal("0.031"), "6억원 이상"),
]

VAT_OPTIONS = {
    "비적용 0%": Decimal("0"),
    "간이과세자 4%": Decimal("0.04"),
    "일반과세자 10%": Decimal("0.10"),
}

DEFAULT_PURCHASE_PRICE = 1_200_000_000
DEFAULT_LEGAL_SERVICE_FEE = 600_000
DEFAULT_OWNERSHIP_REGISTRATION_FEE = 15_000
DEFAULT_MORTGAGE_REGISTRATION_FEE = 15_000
MORTGAGE_BOND_PURCHASE_CAP = 1_000_000_000
MORTGAGE_BOND_MIN_BASE = 20_000_000


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def won(value: Any) -> int:
    return int(as_decimal(value).quantize(WON, rounding=ROUND_HALF_UP))


def money(base: int, rate: Decimal) -> int:
    return won(Decimal(base) * rate)


def format_won(value: int | Decimal) -> str:
    numeric = won(value)
    sign = "-" if numeric < 0 else ""
    return f"{sign}{abs(numeric):,}원"


def format_rate(rate: Decimal, digits: int = 4) -> str:
    percent = rate * Decimal("100")
    text = f"{percent:.{digits}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def find_band(amount: int, bands: list[RateBand]) -> RateBand:
    for band in bands:
        if amount >= band.min_amount and (band.max_amount is None or amount < band.max_amount):
            return band
    raise ValueError(f"No rate band for amount: {amount}")


def find_stamp_band(amount: int) -> StampBand | None:
    for band in STAMP_TAX_BANDS:
        if amount > band.min_exclusive and (
            band.max_inclusive is None or amount <= band.max_inclusive
        ):
            return band
    return None


def calculate_stamp_tax(amount: int) -> tuple[int, str]:
    band = find_stamp_band(amount)
    if band is None:
        return 0, "1천만원 이하"
    return band.tax, band.label


def basic_acquisition_tax_rate(tax_base: int) -> tuple[Decimal, str]:
    if tax_base <= 600_000_000:
        return Decimal("0.01"), "6억원 이하 기본세율"
    if tax_base <= 900_000_000:
        amount_eok = Decimal(tax_base) / EOK
        percent = (amount_eok * Decimal("2") / Decimal("3") - Decimal("3")).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
        return percent / Decimal("100"), "6억원 초과 9억원 이하 비례세율"
    return Decimal("0.03"), "9억원 초과 기본세율"


def acquisition_tax_profile(inputs: PurchaseInputs) -> dict[str, Any]:
    basic_rate, basic_reason = basic_acquisition_tax_rate(inputs.tax_base)

    if inputs.buyer_type == "법인":
        return {
            "rate": Decimal("0.12"),
            "label": "법인 주택 취득 중과",
            "surtax_level": "12%",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }

    count = {"1주택": 1, "2주택": 2, "3주택": 3, "4주택 이상": 4}[inputs.home_count_after]
    if count == 2 and inputs.temporary_two_home:
        return {
            "rate": basic_rate,
            "label": f"일시적 2주택 기본세율 적용 ({basic_reason})",
            "surtax_level": "none",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }
    if inputs.regulated_area and count == 2:
        return {
            "rate": Decimal("0.08"),
            "label": "조정대상지역 2주택 중과",
            "surtax_level": "8%",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }
    if inputs.regulated_area and count >= 3:
        return {
            "rate": Decimal("0.12"),
            "label": "조정대상지역 3주택 이상 중과",
            "surtax_level": "12%",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }
    if not inputs.regulated_area and count == 3:
        return {
            "rate": Decimal("0.08"),
            "label": "비조정지역 3주택 중과",
            "surtax_level": "8%",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }
    if not inputs.regulated_area and count >= 4:
        return {
            "rate": Decimal("0.12"),
            "label": "비조정지역 4주택 이상 중과",
            "surtax_level": "12%",
            "basic_rate": basic_rate,
            "basic_reason": basic_reason,
        }
    return {
        "rate": basic_rate,
        "label": basic_reason,
        "surtax_level": "none",
        "basic_rate": basic_rate,
        "basic_reason": basic_reason,
    }


def round_bond_purchase(raw_amount: int | Decimal) -> int:
    amount = won(raw_amount)
    if amount <= 0:
        return 0
    if amount < 10_000:
        return 10_000
    remainder = amount % 10_000
    base = amount - remainder
    if remainder < 5_000:
        return base
    return base + 10_000


def calculate_brokerage(purchase_price: int, negotiated_rate: Decimal, vat_rate: Decimal) -> dict[str, Any]:
    band = find_band(purchase_price, SEOUL_HOME_BROKERAGE_BANDS)
    base_fee = money(purchase_price, negotiated_rate)
    capped_fee = min(base_fee, band.cap) if band.cap is not None else base_fee
    vat = money(capped_fee, vat_rate)
    return {
        "band": band,
        "base_fee": base_fee,
        "fee": capped_fee,
        "vat": vat,
        "total": capped_fee + vat,
    }


def calculate_ownership_bond(standard_value: int, discount_rate: Decimal) -> dict[str, Any]:
    band = find_band(standard_value, SEOUL_HOME_BOND_BANDS)
    raw_purchase = money(standard_value, band.rate)
    rounded_purchase = round_bond_purchase(raw_purchase)
    discount_cost = money(rounded_purchase, discount_rate)
    return {
        "band": band,
        "raw_purchase": raw_purchase,
        "rounded_purchase": rounded_purchase,
        "discount_cost": discount_cost,
    }


def calculate_mortgage_costs(inputs: PurchaseInputs) -> dict[str, Any]:
    if not inputs.loan_enabled or inputs.loan_amount <= 0:
        return {
            "loan_stamp_total": 0,
            "loan_stamp_buyer": 0,
            "loan_stamp_band": "대출 없음",
            "collateral_amount": 0,
            "registration_license_tax": 0,
            "registration_education_tax": 0,
            "bond_raw_purchase": 0,
            "bond_rounded_purchase": 0,
            "bond_discount_cost": 0,
        }

    collateral_amount = money(inputs.loan_amount, inputs.collateral_ratio)
    loan_stamp_total, loan_stamp_band = calculate_stamp_tax(inputs.loan_amount)
    loan_stamp_buyer = money(loan_stamp_total, inputs.loan_stamp_buyer_share)
    registration_license_tax = money(collateral_amount, Decimal("0.002"))
    registration_education_tax = money(registration_license_tax, Decimal("0.20"))

    if collateral_amount >= MORTGAGE_BOND_MIN_BASE:
        raw_bond_purchase = min(money(collateral_amount, Decimal("0.01")), MORTGAGE_BOND_PURCHASE_CAP)
    else:
        raw_bond_purchase = 0
    rounded_bond_purchase = round_bond_purchase(raw_bond_purchase)
    bond_discount_cost = money(rounded_bond_purchase, inputs.bond_discount_rate)

    return {
        "loan_stamp_total": loan_stamp_total,
        "loan_stamp_buyer": loan_stamp_buyer,
        "loan_stamp_band": loan_stamp_band,
        "collateral_amount": collateral_amount,
        "registration_license_tax": registration_license_tax,
        "registration_education_tax": registration_education_tax,
        "bond_raw_purchase": raw_bond_purchase,
        "bond_rounded_purchase": rounded_bond_purchase,
        "bond_discount_cost": bond_discount_cost,
    }


def add_row(
    rows: list[dict[str, Any]],
    category: str,
    item: str,
    amount: int,
    note: str,
    source: str = "",
) -> None:
    rows.append(
        {
            "구분": category,
            "항목": item,
            "금액": amount,
            "표시금액": format_won(amount),
            "비고": note,
            "근거": source,
        }
    )


def calculate_costs(inputs: PurchaseInputs) -> dict[str, Any]:
    profile = acquisition_tax_profile(inputs)
    tax_rate = profile["rate"]
    gross_acquisition_tax = money(inputs.tax_base, tax_rate)
    acquisition_relief = min(max(inputs.acquisition_tax_relief, 0), gross_acquisition_tax)
    net_acquisition_tax = gross_acquisition_tax - acquisition_relief

    if profile["surtax_level"] == "none":
        local_education_tax = money(Decimal(inputs.tax_base) * tax_rate * Decimal("0.5"), Decimal("0.2"))
        rural_special_rate = Decimal("0.002") if inputs.over_85m2 else Decimal("0")
    else:
        local_education_tax = money(inputs.tax_base, Decimal("0.004"))
        if not inputs.over_85m2:
            rural_special_rate = Decimal("0")
        elif profile["surtax_level"] == "8%":
            rural_special_rate = Decimal("0.006")
        else:
            rural_special_rate = Decimal("0.01")
    rural_special_tax = money(inputs.tax_base, rural_special_rate)

    sale_stamp_total, sale_stamp_band = calculate_stamp_tax(inputs.purchase_price)
    sale_stamp_buyer = money(sale_stamp_total, inputs.sale_stamp_buyer_share)
    brokerage = calculate_brokerage(
        inputs.purchase_price,
        inputs.brokerage_rate,
        inputs.brokerage_vat_rate,
    )
    ownership_bond = calculate_ownership_bond(inputs.bond_standard_value, inputs.bond_discount_rate)
    mortgage = calculate_mortgage_costs(inputs)

    rows: list[dict[str, Any]] = []
    add_row(
        rows,
        "세금",
        "취득세(감면 전)",
        gross_acquisition_tax,
        f"{format_won(inputs.tax_base)} x {format_rate(tax_rate)} / {profile['label']}",
        "지방세법 제11조, 제13조의2",
    )
    if acquisition_relief:
        add_row(
            rows,
            "세금",
            "취득세 감면액(수동 차감)",
            -acquisition_relief,
            "지방교육세·농특세 자동 연동 없이 취득세 본세에서만 차감",
            "사용자 입력",
        )
    add_row(
        rows,
        "세금",
        "지방교육세",
        local_education_tax,
        "기본세율은 취득세율 x 0.5 x 20%, 중과는 과세표준 x 0.4%",
        "지방세법 제151조",
    )
    add_row(
        rows,
        "세금",
        "농어촌특별세",
        rural_special_tax,
        f"전용 85㎡ {'초과' if inputs.over_85m2 else '이하'} / 적용률 {format_rate(rural_special_rate)}",
        "농어촌특별세법 제5조",
    )
    if inputs.relief_related_extra_tax:
        add_row(
            rows,
            "세금",
            "감면 관련 추가 농특세/기타 세액",
            inputs.relief_related_extra_tax,
            "감면별 농특세 부과 여부를 확인해 사용자가 직접 입력",
            "사용자 입력",
        )
    add_row(
        rows,
        "세금",
        "매매계약 인지세(사용자 부담분)",
        sale_stamp_buyer,
        f"전체 {format_won(sale_stamp_total)} / {sale_stamp_band} / 부담률 {format_rate(inputs.sale_stamp_buyer_share)}",
        "인지세법 제3조",
    )

    add_row(
        rows,
        "거래/등기",
        "중개보수",
        brokerage["fee"],
        f"협의율 {format_rate(inputs.brokerage_rate)} / 법정상한 {format_rate(brokerage['band'].rate)} ({brokerage['band'].label})",
        "공인중개사법, 서울특별시 주택 중개보수 등에 관한 조례",
    )
    if brokerage["vat"]:
        add_row(
            rows,
            "거래/등기",
            "중개보수 부가가치세",
            brokerage["vat"],
            f"중개보수 x {format_rate(inputs.brokerage_vat_rate)}",
            "사용자 선택",
        )
    add_row(
        rows,
        "거래/등기",
        "국민주택채권 할인비용(소유권 이전)",
        ownership_bond["discount_cost"],
        (
            f"매입액 {format_won(ownership_bond['rounded_purchase'])} x "
            f"할인율 {format_rate(inputs.bond_discount_rate)}"
        ),
        "주택도시기금법 시행령 별표",
    )
    add_row(
        rows,
        "거래/등기",
        "소유권 이전 등기신청수수료",
        inputs.ownership_registration_fee,
        "전자/방문 신청 방식에 따라 달라질 수 있음",
        "사용자 입력",
    )
    add_row(
        rows,
        "거래/등기",
        "법무사 보수",
        inputs.legal_service_fee,
        "견적 기준으로 수정",
        "사용자 입력",
    )
    if inputs.other_transaction_fee:
        add_row(
            rows,
            "거래/등기",
            "기타 거래 비용",
            inputs.other_transaction_fee,
            "이사비, 서류 발급, 확인 비용 등",
            "사용자 입력",
        )

    if inputs.loan_enabled and inputs.loan_amount > 0:
        add_row(
            rows,
            "대출",
            "대출계약 인지세(사용자 부담분)",
            mortgage["loan_stamp_buyer"],
            (
                f"전체 {format_won(mortgage['loan_stamp_total'])} / "
                f"{mortgage['loan_stamp_band']} / 부담률 {format_rate(inputs.loan_stamp_buyer_share)}"
            ),
            "인지세법 제3조",
        )
        add_row(
            rows,
            "대출",
            "근저당 등록면허세",
            mortgage["registration_license_tax"],
            f"채권최고액 {format_won(mortgage['collateral_amount'])} x 0.2%",
            "지방세법 제28조",
        )
        add_row(
            rows,
            "대출",
            "근저당 지방교육세",
            mortgage["registration_education_tax"],
            "등록면허세 x 20%",
            "지방세법 제151조",
        )
        add_row(
            rows,
            "대출",
            "국민주택채권 할인비용(저당권 설정)",
            mortgage["bond_discount_cost"],
            (
                f"매입액 {format_won(mortgage['bond_rounded_purchase'])} x "
                f"할인율 {format_rate(inputs.bond_discount_rate)}"
            ),
            "주택도시기금법 시행령 별표",
        )
        add_row(
            rows,
            "대출",
            "근저당 등기신청수수료",
            inputs.mortgage_registration_fee,
            "전자/방문 신청 방식에 따라 달라질 수 있음",
            "사용자 입력",
        )
        if inputs.loan_other_fee:
            add_row(
                rows,
                "대출",
                "보증료/감정료/기타 대출 비용",
                inputs.loan_other_fee,
                "은행 견적 기준으로 수정",
                "사용자 입력",
            )

    tax_total = sum(row["금액"] for row in rows if row["구분"] == "세금")
    transaction_total = sum(row["금액"] for row in rows if row["구분"] == "거래/등기")
    loan_total = sum(row["금액"] for row in rows if row["구분"] == "대출")
    total_cost = tax_total + transaction_total + loan_total
    effective_loan = min(inputs.loan_amount if inputs.loan_enabled else 0, inputs.purchase_price)
    cash_needed = inputs.purchase_price - effective_loan + total_cost

    return {
        "profile": profile,
        "gross_acquisition_tax": gross_acquisition_tax,
        "acquisition_relief": acquisition_relief,
        "net_acquisition_tax": net_acquisition_tax,
        "local_education_tax": local_education_tax,
        "rural_special_tax": rural_special_tax,
        "sale_stamp_total": sale_stamp_total,
        "sale_stamp_buyer": sale_stamp_buyer,
        "brokerage": brokerage,
        "ownership_bond": ownership_bond,
        "mortgage": mortgage,
        "rows": rows,
        "summary": {
            "tax_total": tax_total,
            "transaction_total": transaction_total,
            "loan_total": loan_total,
            "total_cost": total_cost,
            "cash_needed": cash_needed,
            "effective_loan": effective_loan,
        },
    }


def rows_to_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["구분", "항목", "금액", "표시금액", "비고", "근거"])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def run_self_tests() -> None:
    base = PurchaseInputs(
        purchase_price=500_000_000,
        tax_base=500_000_000,
        bond_standard_value=350_000_000,
        over_85m2=False,
        buyer_type="개인",
        home_count_after="1주택",
        regulated_area=False,
        temporary_two_home=False,
        brokerage_rate=Decimal("0.004"),
        brokerage_vat_rate=Decimal("0.10"),
        bond_discount_rate=Decimal("0.11"),
        acquisition_tax_relief=0,
        relief_related_extra_tax=0,
        sale_stamp_buyer_share=Decimal("0.5"),
        legal_service_fee=0,
        ownership_registration_fee=0,
        other_transaction_fee=0,
        loan_enabled=False,
        loan_amount=0,
        collateral_ratio=Decimal("1.2"),
        loan_stamp_buyer_share=Decimal("0.5"),
        mortgage_registration_fee=0,
        loan_other_fee=0,
    )
    result = calculate_costs(base)
    assert result["profile"]["rate"] == Decimal("0.01")
    assert result["gross_acquisition_tax"] == 5_000_000
    assert result["local_education_tax"] == 500_000
    assert result["rural_special_tax"] == 0

    case_800m = PurchaseInputs(
        **{
            **base.__dict__,
            "purchase_price": 800_000_000,
            "tax_base": 800_000_000,
            "bond_standard_value": 560_000_000,
            "over_85m2": True,
        }
    )
    result = calculate_costs(case_800m)
    assert result["profile"]["rate"] == Decimal("0.023333")
    assert result["gross_acquisition_tax"] == 18_666_400
    assert result["local_education_tax"] == 1_866_640
    assert result["rural_special_tax"] == 1_600_000

    case_surtax = PurchaseInputs(
        **{
            **base.__dict__,
            "purchase_price": 1_200_000_000,
            "tax_base": 1_200_000_000,
            "bond_standard_value": 900_000_000,
            "over_85m2": True,
            "home_count_after": "2주택",
            "regulated_area": True,
        }
    )
    result = calculate_costs(case_surtax)
    assert result["profile"]["rate"] == Decimal("0.08")
    assert result["gross_acquisition_tax"] == 96_000_000
    assert result["local_education_tax"] == 4_800_000
    assert result["rural_special_tax"] == 7_200_000

    case_loan = PurchaseInputs(
        **{
            **base.__dict__,
            "purchase_price": 1_600_000_000,
            "tax_base": 1_600_000_000,
            "bond_standard_value": 1_100_000_000,
            "loan_enabled": True,
            "loan_amount": 800_000_000,
            "collateral_ratio": Decimal("1.2"),
        }
    )
    result = calculate_costs(case_loan)
    assert result["gross_acquisition_tax"] == 48_000_000
    assert result["mortgage"]["collateral_amount"] == 960_000_000
    assert result["mortgage"]["registration_license_tax"] == 1_920_000
    assert result["mortgage"]["registration_education_tax"] == 384_000
    assert result["mortgage"]["bond_rounded_purchase"] == 9_600_000
    assert result["mortgage"]["bond_discount_cost"] == 1_056_000
    assert result["mortgage"]["loan_stamp_buyer"] == 75_000

    assert round_bond_purchase(0) == 0
    assert round_bond_purchase(4_999) == 10_000
    assert round_bond_purchase(5_000) == 10_000
    assert round_bond_purchase(14_999) == 10_000
    assert round_bond_purchase(15_000) == 20_000

    print("self-test passed")


def render_metric_row(st: Any, summary: dict[str, int]) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 필요 현금", format_won(summary["cash_needed"]))
    col2.metric("취득 관련 세금", format_won(summary["tax_total"]))
    col3.metric("거래/등기비", format_won(summary["transaction_total"]))
    col4.metric("대출 관련 비용", format_won(summary["loan_total"]))


def run_app() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="서울 주택 구매비용 계산기",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1260px;
            padding-top: 1.7rem;
            padding-bottom: 3rem;
        }
        h1, h2, h3 {
            letter-spacing: 0;
        }
        div[data-testid="stMetric"] {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 16px;
        }
        div[data-testid="stMetric"] label {
            color: #475569;
        }
        .notice {
            border-left: 4px solid #0f766e;
            background: #f0fdfa;
            padding: 12px 14px;
            border-radius: 6px;
            color: #134e4a;
            margin: 0.5rem 0 1rem 0;
        }
        .subtle {
            color: #64748b;
            font-size: 0.92rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("서울 주택 구매비용 계산기")
    st.caption(
        "서울 소재 주택 매매 시 필요한 취득세, 중개보수, 국민주택채권, 대출 근저당 비용을 한 번에 계산합니다."
    )
    st.markdown(
        """
        <div class="notice">
        감면은 자동 판정하지 않습니다. 입력한 취득세 감면액은 취득세 본세에서만 단순 차감하며,
        지방교육세 비례 감면 또는 감면분 농어촌특별세 부과는 별도 입력으로 반영하세요.
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([0.92, 1.38], gap="large")

    with left:
        st.subheader("입력")
        with st.expander("거래 기본정보", expanded=True):
            purchase_price = st.number_input(
                "매매가",
                min_value=0,
                value=DEFAULT_PURCHASE_PRICE,
                step=10_000_000,
                format="%d",
                help="실제 계약금액 기준입니다.",
            )
            use_purchase_as_tax_base = st.checkbox("취득세 과세표준을 매매가와 동일하게 계산", value=True)
            if use_purchase_as_tax_base:
                tax_base = int(purchase_price)
                st.caption(f"취득세 과세표준: {format_won(tax_base)}")
            else:
                tax_base = st.number_input(
                    "취득세 과세표준",
                    min_value=0,
                    value=int(purchase_price),
                    step=10_000_000,
                    format="%d",
                )
            estimated_standard_value = won(Decimal(int(purchase_price)) * Decimal("0.70"))
            bond_standard_value = st.number_input(
                "국민주택채권 기준 시가표준액",
                min_value=0,
                value=estimated_standard_value,
                step=10_000_000,
                format="%d",
                help="공동주택가격 등 실제 시가표준액을 입력하세요. 기본값은 임시 추정치입니다.",
            )
            area_choice = st.radio(
                "전용면적",
                ["85㎡ 이하", "85㎡ 초과"],
                horizontal=True,
                help="농어촌특별세 적용 여부에 사용됩니다.",
            )

        with st.expander("취득세 판단", expanded=True):
            buyer_type = st.radio("취득자", ["개인", "법인"], horizontal=True)
            home_count_after = st.selectbox(
                "취득 후 주택 수",
                ["1주택", "2주택", "3주택", "4주택 이상"],
                help="세대 기준 주택 수를 입력합니다. 법인은 주택 수와 무관하게 중과로 계산합니다.",
            )
            regulated_area = st.checkbox(
                "조정대상지역으로 계산",
                value=False,
                help="거래일 기준 조정대상지역 여부를 직접 확인해 선택하세요.",
            )
            temporary_two_home = st.checkbox(
                "일시적 2주택으로 기본세율 적용",
                value=False,
                disabled=buyer_type == "법인" or home_count_after != "2주택",
                help="요건 충족 여부는 사용자가 별도로 확인해야 합니다.",
            )
            acquisition_tax_relief = st.number_input(
                "취득세 감면액",
                min_value=0,
                value=0,
                step=100_000,
                format="%d",
                help="취득세 본세에서만 단순 차감합니다.",
            )
            relief_related_extra_tax = st.number_input(
                "감면 관련 추가 농특세/기타 세액",
                min_value=0,
                value=0,
                step=100_000,
                format="%d",
                help="감면분 농특세 등 별도 확인된 추가 세액을 입력합니다.",
            )

        with st.expander("중개보수 및 채권", expanded=True):
            brokerage_band = find_band(int(purchase_price), SEOUL_HOME_BROKERAGE_BANDS)
            st.caption(
                f"서울 주택 매매 중개보수 상한: {format_rate(brokerage_band.rate)}"
                + (f", 한도 {format_won(brokerage_band.cap)}" if brokerage_band.cap else "")
            )
            max_brokerage_percent = float(brokerage_band.rate * Decimal("100"))
            brokerage_rate_percent = st.number_input(
                "실제 적용 중개보수율(%)",
                min_value=0.0,
                max_value=max_brokerage_percent,
                value=max_brokerage_percent,
                step=0.01,
                format="%.3f",
            )
            vat_choice = st.selectbox(
                "중개보수 VAT",
                list(VAT_OPTIONS.keys()),
                index=2,
                help="중개사의 과세 유형에 맞춰 선택하세요.",
            )
            bond_discount_percent = st.number_input(
                "국민주택채권 즉시매도 할인율(%)",
                min_value=0.0,
                max_value=100.0,
                value=11.0,
                step=0.1,
                format="%.2f",
                help="일별로 변동됩니다. 주택도시기금 또는 은행 고시값으로 수정하세요.",
            )
            sale_stamp_buyer_share_percent = st.number_input(
                "매매계약 인지세 부담률(%)",
                min_value=0.0,
                max_value=100.0,
                value=50.0,
                step=5.0,
                format="%.1f",
            )

        with st.expander("대출 및 근저당", expanded=False):
            loan_enabled = st.checkbox("대출 있음", value=True)
            if loan_enabled:
                default_loan = min(700_000_000, int(purchase_price))
                loan_amount = st.number_input(
                    "대출금",
                    min_value=0,
                    value=default_loan,
                    step=10_000_000,
                    format="%d",
                )
                collateral_ratio_percent = st.number_input(
                    "채권최고액 비율(%)",
                    min_value=0.0,
                    value=120.0,
                    step=5.0,
                    format="%.1f",
                )
                loan_stamp_buyer_share_percent = st.number_input(
                    "대출 인지세 부담률(%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=50.0,
                    step=5.0,
                    format="%.1f",
                )
                mortgage_registration_fee = st.number_input(
                    "근저당 등기신청수수료",
                    min_value=0,
                    value=DEFAULT_MORTGAGE_REGISTRATION_FEE,
                    step=1_000,
                    format="%d",
                )
                loan_other_fee = st.number_input(
                    "보증료/감정료/기타 대출 비용",
                    min_value=0,
                    value=0,
                    step=10_000,
                    format="%d",
                )
            else:
                loan_amount = 0
                collateral_ratio_percent = 120.0
                loan_stamp_buyer_share_percent = 50.0
                mortgage_registration_fee = 0
                loan_other_fee = 0

        with st.expander("법무사 및 기타", expanded=False):
            ownership_registration_fee = st.number_input(
                "소유권 이전 등기신청수수료",
                min_value=0,
                value=DEFAULT_OWNERSHIP_REGISTRATION_FEE,
                step=1_000,
                format="%d",
            )
            legal_service_fee = st.number_input(
                "법무사 보수",
                min_value=0,
                value=DEFAULT_LEGAL_SERVICE_FEE,
                step=10_000,
                format="%d",
                help="견적을 받으면 해당 금액으로 수정하세요.",
            )
            other_transaction_fee = st.number_input(
                "기타 거래 비용",
                min_value=0,
                value=0,
                step=10_000,
                format="%d",
            )

    inputs = PurchaseInputs(
        purchase_price=int(purchase_price),
        tax_base=int(tax_base),
        bond_standard_value=int(bond_standard_value),
        over_85m2=area_choice == "85㎡ 초과",
        buyer_type=buyer_type,
        home_count_after=home_count_after,
        regulated_area=regulated_area,
        temporary_two_home=temporary_two_home and buyer_type != "법인" and home_count_after == "2주택",
        brokerage_rate=Decimal(str(brokerage_rate_percent)) / Decimal("100"),
        brokerage_vat_rate=VAT_OPTIONS[vat_choice],
        bond_discount_rate=Decimal(str(bond_discount_percent)) / Decimal("100"),
        acquisition_tax_relief=int(acquisition_tax_relief),
        relief_related_extra_tax=int(relief_related_extra_tax),
        sale_stamp_buyer_share=Decimal(str(sale_stamp_buyer_share_percent)) / Decimal("100"),
        legal_service_fee=int(legal_service_fee),
        ownership_registration_fee=int(ownership_registration_fee),
        other_transaction_fee=int(other_transaction_fee),
        loan_enabled=loan_enabled,
        loan_amount=int(loan_amount),
        collateral_ratio=Decimal(str(collateral_ratio_percent)) / Decimal("100"),
        loan_stamp_buyer_share=Decimal(str(loan_stamp_buyer_share_percent)) / Decimal("100"),
        mortgage_registration_fee=int(mortgage_registration_fee),
        loan_other_fee=int(loan_other_fee),
    )
    result = calculate_costs(inputs)
    rows = result["rows"]
    summary = result["summary"]

    with right:
        st.subheader("결과")
        render_metric_row(st, summary)
        st.caption(
            f"총 비용 {format_won(summary['total_cost'])} + 매매가 {format_won(inputs.purchase_price)}"
            f" - 반영 대출금 {format_won(summary['effective_loan'])}"
        )

        tab_breakdown, tab_formula, tab_sources = st.tabs(["Breakdown", "산식", "근거"])
        with tab_breakdown:
            display_rows = [
                {
                    "구분": row["구분"],
                    "항목": row["항목"],
                    "금액": row["표시금액"],
                    "비고": row["비고"],
                }
                for row in rows
            ]
            st.dataframe(display_rows, use_container_width=True, hide_index=True)
            csv_data = rows_to_csv(rows).encode("utf-8-sig")
            st.download_button(
                "CSV 다운로드",
                data=csv_data,
                file_name="seoul_home_purchase_cost_breakdown.csv",
                mime="text/csv",
            )

            st.markdown("#### 주요 계산값")
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.write(f"적용 취득세율: **{format_rate(result['profile']['rate'])}**")
                st.write(f"취득세 감면 후 본세: **{format_won(result['net_acquisition_tax'])}**")
                st.write(
                    "소유권 이전 국민주택채권 매입액: "
                    f"**{format_won(result['ownership_bond']['rounded_purchase'])}**"
                )
            with detail_col2:
                st.write(
                    "중개보수 합계: "
                    f"**{format_won(result['brokerage']['total'])}**"
                )
                if inputs.loan_enabled and inputs.loan_amount > 0:
                    st.write(
                        "채권최고액: "
                        f"**{format_won(result['mortgage']['collateral_amount'])}**"
                    )
                    st.write(
                        "저당권 국민주택채권 매입액: "
                        f"**{format_won(result['mortgage']['bond_rounded_purchase'])}**"
                    )
                else:
                    st.write("대출 관련 계산: **대출 없음**")

        with tab_formula:
            st.markdown(
                f"""
                #### 취득세
                - 적용 판단: `{result['profile']['label']}`
                - 과세표준 `{format_won(inputs.tax_base)}` x `{format_rate(result['profile']['rate'])}`
                - 감면액은 취득세 본세에서만 차감: `{format_won(result['gross_acquisition_tax'])}` - `{format_won(result['acquisition_relief'])}`

                #### 지방교육세와 농어촌특별세
                - 기본세율 지방교육세: `과세표준 x 취득세율 x 0.5 x 0.2`
                - 중과세율 지방교육세: `과세표준 x 0.4%`
                - 농어촌특별세: 85㎡ 이하는 0원, 85㎡ 초과는 기본 0.2% / 8% 중과 0.6% / 12% 중과 1.0%

                #### 국민주택채권
                - 소유권 이전: 시가표준액 `{format_won(inputs.bond_standard_value)}` x 서울·광역시 주택 매입률
                - 단수 처리: 0원은 0원, 0원 초과 1만원 미만은 1만원, 1만원 이상은 1만원 단위 반올림
                - 즉시매도 비용: 채권 매입액 x 할인율 `{format_rate(inputs.bond_discount_rate)}`

                #### 대출
                - 채권최고액: 대출금 x 채권최고액 비율
                - 근저당 등록면허세: 채권최고액 x 0.2%
                - 근저당 지방교육세: 등록면허세 x 20%
                - 저당권 국민주택채권: 채권최고액 x 1%, 매입액 상한 10억원
                """
            )

        with tab_sources:
            st.markdown(
                """
                - 취득세·인지세·지방교육세·농어촌특별세 개요: [찾기쉬운 생활법령정보](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=3&cnpClsNo=2&csmSeq=534&menuType=cnpcls&popMenu=ov)
                - 다주택 중과: [지방세법 제13조의2](https://law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1020081767)
                - 중개보수: [찾기쉬운 생활법령정보 - 부동산 중개보수 산정](https://www.easylaw.go.kr/CSP/CnpClsMain.laf?ccfNo=2&cciNo=2&cnpClsNo=2&csmSeq=649&popMenu=ov)
                - 국민주택채권 조회: [주택도시기금 매입대상금액조회](https://nhuf.molit.go.kr/FP/FP07/FP0705/FP070504.jsp)
                - 국민주택채권 매입률 별표: [주택도시기금법 시행령 별표](https://www.law.go.kr/LSW/flDownload.do?bylClsCd=110201&flSeq=33335725&gubun=)

                이 계산기는 사전 검토용입니다. 실제 신고·납부 전에는 관할 구청, 세무사, 법무사, 금융기관 고지액을 확인하세요.
                """
            )


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_self_tests()
    else:
        run_app()
