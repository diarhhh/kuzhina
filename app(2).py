
import io
import math
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple

import pandas as pd
import streamlit as st


# ============================================================
# APP CONFIG
# ============================================================
st.set_page_config(
    page_title="WoodCut Pro - Kitchen Cabinet Calculator",
    page_icon="🪚",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# DATA MODELS
# ============================================================
@dataclass
class CutPart:
    name: str
    qty: int
    height_mm: float
    width_mm: float
    material: str
    edge_banding: str
    edge_length_m: float = 0.0

    @property
    def area_m2(self) -> float:
        return (self.height_mm * self.width_mm * self.qty) / 1_000_000


@dataclass
class HardwareSummary:
    hinges: int = 0
    handles: int = 0
    drawer_runner_sets: int = 0
    runner_length_mm: int = 0
    legs: int = 4
    abs_m: float = 0.0


# ============================================================
# CONSTANTS / BUSINESS RULES
# ============================================================
BOARD_THICKNESSES = [16, 18, 19]
ABS_THICKNESSES = [0.0, 0.4, 1.0, 2.0]
RUNNER_LENGTHS = [400, 450, 500, 550]

MIN_H = 250
MAX_H = 2600
MIN_W = 150
MAX_W = 1800
MIN_D = 200
MAX_D = 900

DOOR_GAP_DEFAULT = 3.0
DRAWER_FRONT_GAP_DEFAULT = 3.0
BACK_PANEL_THICKNESS = 3.0
BACK_GROOVE_DEPTH = 8.0
BACK_REAR_CLEARANCE = 3.0
SHELF_FRONT_CLEARANCE = 2.0
DRAWER_RUNNER_CLEARANCE_TOTAL = 25.0
DRAWER_BOX_SIDE_THICKNESS = 16.0
DRAWER_BOX_BOTTOM_THICKNESS = 3.0


# ============================================================
# HELPERS
# ============================================================
def mm(value: float) -> float:
    return round(float(value), 1)


def positive_dimension(value: float, label: str) -> None:
    if value <= 0:
        raise ValueError(f"{label} duhet të jetë më e madhe se 0 mm.")


def validate_dimensions(h: float, w: float, d: float, t: float) -> None:
    errors = []

    if not (MIN_H <= h <= MAX_H):
        errors.append(f"Lartësia duhet të jetë ndërmjet {MIN_H} dhe {MAX_H} mm.")
    if not (MIN_W <= w <= MAX_W):
        errors.append(f"Gjerësia duhet të jetë ndërmjet {MIN_W} dhe {MAX_W} mm.")
    if not (MIN_D <= d <= MAX_D):
        errors.append(f"Thellësia duhet të jetë ndërmjet {MIN_D} dhe {MAX_D} mm.")
    if w <= 2 * t + 50:
        errors.append("Gjerësia është shumë e vogël në raport me trashësinë e pllakës.")
    if h <= t + 50:
        errors.append("Lartësia është shumë e vogël për një korpus funksional.")
    if d <= 100:
        errors.append("Thellësia është joreale për këtë lloj elementi.")

    if errors:
        raise ValueError("\n".join(errors))


def edge_adjust(size_mm: float, banded_edges_count: int, abs_mm: float) -> float:
    """
    Zbrit trashësinë e ABS-it vetëm në skajet që kantohen
    dhe që ndikojnë në dimensionin përkatës.
    """
    adjusted = size_mm - (banded_edges_count * abs_mm)
    if adjusted <= 0:
        raise ValueError("Trashësia e ABS-it prodhon masë prerjeje jo valide.")
    return mm(adjusted)


def calc_edge_length_m(height_mm: float, width_mm: float, qty: int, edges: str) -> float:
    """
    edges:
      '0' = pa kant
      '1H' = një anë në dimensionin H
      '2H' = dy anë në dimensionin H
      '1W' = një anë në dimensionin W
      '2W' = dy anë në dimensionin W
      '4' = të katër anët
      '2H+1W', etj.
    """
    total_mm_per_piece = 0.0
    tokens = edges.split("+") if "+" in edges else [edges]

    for token in tokens:
        token = token.strip()
        if token == "0" or token == "":
            continue
        if token == "4":
            total_mm_per_piece += 2 * height_mm + 2 * width_mm
        elif token.endswith("H"):
            count = int(token[:-1])
            total_mm_per_piece += count * height_mm
        elif token.endswith("W"):
            count = int(token[:-1])
            total_mm_per_piece += count * width_mm

    return round((total_mm_per_piece * qty) / 1000, 3)


def add_part(
    parts: List[CutPart],
    name: str,
    qty: int,
    h: float,
    w: float,
    material: str,
    edge_desc: str,
    edge_rule: str,
) -> None:
    positive_dimension(h, f"Lartësia e copës '{name}'")
    positive_dimension(w, f"Gjerësia e copës '{name}'")

    edge_len = calc_edge_length_m(h, w, qty, edge_rule)

    parts.append(
        CutPart(
            name=name,
            qty=int(qty),
            height_mm=mm(h),
            width_mm=mm(w),
            material=material,
            edge_banding=edge_desc,
            edge_length_m=edge_len,
        )
    )


def select_runner_length(depth_mm: float) -> int:
    """
    Zgjedh gjatësinë më të madhe standarde që futet në korpus,
    duke lënë rreth 20 mm rezervë prapa.
    """
    usable = depth_mm - 20
    valid = [r for r in RUNNER_LENGTHS if r <= usable]
    return max(valid) if valid else RUNNER_LENGTHS[0]


def hinges_per_door(height_mm: float) -> int:
    if height_mm < 1000:
        return 2
    if height_mm <= 1500:
        return 3
    return 4


# ============================================================
# CUT LIST ENGINE
# ============================================================
def build_cut_list(
    h: float,
    w: float,
    d: float,
    t: float,
    abs_t: float,
    element_type: str,
    door_count: int,
    shelf_count: int,
    drawer_count: int,
    back_type: str,
    door_gap: float,
    drawer_gap: float,
) -> Tuple[List[CutPart], HardwareSummary]:
    validate_dimensions(h, w, d, t)

    parts: List[CutPart] = []

    # Korpusi - anësoret:
    # Kantohet vetëm skaji frontal. ABS ndikon në thellësi.
    side_cut_depth = edge_adjust(d, 1, abs_t)
    add_part(
        parts,
        "Anësore korpusi",
        2,
        h,
        side_cut_depth,
        "MDF / Ivericë",
        "1 anë frontale",
        "1H",
    )

    # Baza / fundi
    inner_width = w - (2 * t)
    base_width_cut = edge_adjust(inner_width, 0, abs_t)
    base_depth_cut = edge_adjust(d, 1, abs_t)
    add_part(
        parts,
        "Baza / fundi",
        1,
        base_width_cut,
        base_depth_cut,
        "MDF / Ivericë",
        "1 anë frontale",
        "1H",
    )

    # Traversat e sipërme - 2 copë, tipike për element të poshtëm
    traverse_depth = 100.0
    traverse_width_cut = edge_adjust(inner_width, 0, abs_t)
    traverse_depth_cut = edge_adjust(traverse_depth, 1, abs_t)
    add_part(
        parts,
        "Traversë lidhëse sipër",
        2,
        traverse_width_cut,
        traverse_depth_cut,
        "MDF / Ivericë",
        "1 anë e dukshme",
        "1H",
    )

    # Prapavija
    if back_type == "Lesonit 3mm me kanal (sofit)":
        # Paneli hyn në kanal rreth 8 mm nga secila anë.
        back_h = h - 2 * BACK_GROOVE_DEPTH
        back_w = w - 2 * BACK_GROOVE_DEPTH
        usable_inside_depth = d - BACK_GROOVE_DEPTH
    else:
        # Panel i vendosur mbi korpus, pak më i vogël që të mos dalë jashtë.
        back_h = h - 2
        back_w = w - 2
        usable_inside_depth = d - BACK_REAR_CLEARANCE

    add_part(
        parts,
        "Prapavijë",
        1,
        back_h,
        back_w,
        "Lesonit 3mm",
        "Pa kant",
        "0",
    )

    # Raftet
    if shelf_count > 0:
        shelf_h = inner_width
        shelf_d = usable_inside_depth - SHELF_FRONT_CLEARANCE
        shelf_d = edge_adjust(shelf_d, 1, abs_t)

        add_part(
            parts,
            "Raft i brendshëm",
            shelf_count,
            shelf_h,
            shelf_d,
            "MDF / Ivericë",
            "1 anë frontale",
            "1H",
        )

    hardware = HardwareSummary()
    hardware.legs = 4

    if element_type == "Element me Dyer":
        # Frontet mbulojnë korpusin (overlay), me fuga.
        front_h = h - (2 * door_gap)

        if door_count == 1:
            front_w = w - (2 * door_gap)
            front_w_cut = edge_adjust(front_w, 2, abs_t)
            front_h_cut = edge_adjust(front_h, 2, abs_t)

            add_part(
                parts,
                "Derë",
                1,
                front_h_cut,
                front_w_cut,
                "MDF / Ivericë",
                "4 anë",
                "4",
            )
        else:
            # 2 fuga anësore + një fugë qendrore
            total_gap = (2 * door_gap) + door_gap
            front_w = (w - total_gap) / 2

            front_w_cut = edge_adjust(front_w, 2, abs_t)
            front_h_cut = edge_adjust(front_h, 2, abs_t)

            add_part(
                parts,
                "Derë",
                2,
                front_h_cut,
                front_w_cut,
                "MDF / Ivericë",
                "4 anë",
                "4",
            )

        hardware.hinges = hinges_per_door(front_h) * door_count
        hardware.handles = door_count

    else:
        # Frontet e sirtarëve ndahen vertikalisht në lartësinë e korpusit.
        total_vertical_gap = drawer_gap * (drawer_count + 1)
        front_h_nominal = (h - total_vertical_gap) / drawer_count
        front_w_nominal = w - (2 * drawer_gap)

        front_h_cut = edge_adjust(front_h_nominal, 2, abs_t)
        front_w_cut = edge_adjust(front_w_nominal, 2, abs_t)

        add_part(
            parts,
            "Front sirtari",
            drawer_count,
            front_h_cut,
            front_w_cut,
            "MDF / Ivericë",
            "4 anë",
            "4",
        )

        runner_length = select_runner_length(d)
        hardware.runner_length_mm = runner_length
        hardware.drawer_runner_sets = drawer_count
        hardware.handles = drawer_count

        # Kutitë e sirtarëve.
        # Gjerësia e kutisë = hapësira e brendshme - 25 mm për shinat.
        drawer_outer_w = inner_width - DRAWER_RUNNER_CLEARANCE_TOTAL
        if drawer_outer_w <= 100:
            raise ValueError("Gjerësia e sirtarit është shumë e vogël pas zbritjes për shina.")

        # Thellësia e kutisë i përshtatet shinës.
        drawer_box_depth = runner_length

        # Lartësia praktike e kutisë: e kufizuar nga fronti dhe maksimumi 180 mm.
        drawer_side_height = min(180.0, max(80.0, front_h_nominal - 35.0))

        # Anësoret e sirtarit
        add_part(
            parts,
            "Anësore kutie sirtari",
            drawer_count * 2,
            drawer_box_depth,
            drawer_side_height,
            "MDF / Ivericë",
            "1 anë sipër",
            "1H",
        )

        # Para / prapa futen mes anësoreve.
        drawer_inner_piece_w = drawer_outer_w - (2 * DRAWER_BOX_SIDE_THICKNESS)

        add_part(
            parts,
            "Para / Prapa kutie sirtari",
            drawer_count * 2,
            drawer_inner_piece_w,
            drawer_side_height,
            "MDF / Ivericë",
            "1 anë sipër",
            "1H",
        )

        # Fundi 3 mm
        drawer_bottom_w = drawer_outer_w
        drawer_bottom_d = drawer_box_depth

        add_part(
            parts,
            "Fund kutie sirtari",
            drawer_count,
            drawer_bottom_d,
            drawer_bottom_w,
            "Lesonit 3mm",
            "Pa kant",
            "0",
        )

    hardware.abs_m = round(sum(p.edge_length_m for p in parts), 3)
    return parts, hardware


# ============================================================
# COST ENGINE
# ============================================================
def calculate_costs(
    parts: List[CutPart],
    hardware: HardwareSummary,
    board_price_m2: float,
    hardboard_price_m2: float,
    hinge_price: float,
    handle_price: float,
    runner_set_price: float,
    leg_price: float,
    abs_price_m: float,
    waste_percent: float,
    profit_percent: float,
) -> Dict[str, float]:
    board_net = sum(p.area_m2 for p in parts if p.material == "MDF / Ivericë")
    hardboard_net = sum(p.area_m2 for p in parts if p.material == "Lesonit 3mm")

    waste_factor = 1 + (waste_percent / 100.0)

    board_gross = board_net * waste_factor
    hardboard_gross = hardboard_net * waste_factor

    board_cost = board_gross * board_price_m2
    hardboard_cost = hardboard_gross * hardboard_price_m2

    hardware_cost = (
        hardware.hinges * hinge_price
        + hardware.handles * handle_price
        + hardware.drawer_runner_sets * runner_set_price
        + hardware.legs * leg_price
        + hardware.abs_m * abs_price_m
    )

    total_material_cost = board_cost + hardboard_cost + hardware_cost

    # Profit / work markup applied on top of total cost.
    profit_value = total_material_cost * (profit_percent / 100.0)
    final_price = total_material_cost + profit_value

    return {
        "board_net_m2": board_net,
        "hardboard_net_m2": hardboard_net,
        "net_total_m2": board_net + hardboard_net,
        "board_gross_m2": board_gross,
        "hardboard_gross_m2": hardboard_gross,
        "gross_total_m2": board_gross + hardboard_gross,
        "board_cost": board_cost,
        "hardboard_cost": hardboard_cost,
        "hardware_cost": hardware_cost,
        "total_material_cost": total_material_cost,
        "profit_value": profit_value,
        "final_price": final_price,
    }


# ============================================================
# EXPORTS
# ============================================================
def cut_list_dataframe(parts: List[CutPart]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Emri i copës": p.name,
                "Sasia": p.qty,
                "Lartësia mm": p.height_mm,
                "Gjerësia mm": p.width_mm,
                "Materiali": p.material,
                "Anët e kantimit": p.edge_banding,
                "ABS m": p.edge_length_m,
                "Sipërfaqe m²": round(p.area_m2, 4),
            }
            for p in parts
        ]
    )


def hardware_dataframe(hw: HardwareSummary) -> pd.DataFrame:
    rows = [
        {"Aksesori": "Bagllama", "Sasia": hw.hinges, "Njësia": "copë"},
        {"Aksesori": "Doreza", "Sasia": hw.handles, "Njësia": "copë"},
        {"Aksesori": "Shina sirtari", "Sasia": hw.drawer_runner_sets, "Njësia": "sete"},
        {"Aksesori": "Këmbë rregulluese", "Sasia": hw.legs, "Njësia": "copë"},
        {"Aksesori": "Shirit ABS", "Sasia": hw.abs_m, "Njësia": "m"},
    ]
    if hw.drawer_runner_sets > 0:
        rows[2]["Specifikimi"] = f"{hw.runner_length_mm} mm"
    return pd.DataFrame(rows)


def make_excel_bytes(
    cut_df: pd.DataFrame,
    hardware_df: pd.DataFrame,
    costs: Dict[str, float],
    project_name: str,
) -> bytes:
    output = io.BytesIO()

    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            cut_df.to_excel(writer, sheet_name="Lista e prerjeve", index=False)
            hardware_df.to_excel(writer, sheet_name="Aksesoret", index=False)

            summary_df = pd.DataFrame(
                [
                    ["Projekti", project_name],
                    ["Sipërfaqja neto m²", round(costs["net_total_m2"], 3)],
                    ["Sipërfaqja bruto m²", round(costs["gross_total_m2"], 3)],
                    ["Kosto materiali €", round(costs["total_material_cost"], 2)],
                    ["Fitimi / puna €", round(costs["profit_value"], 2)],
                    ["Oferta finale €", round(costs["final_price"], 2)],
                ],
                columns=["Përshkrimi", "Vlera"],
            )
            summary_df.to_excel(writer, sheet_name="Oferta", index=False)

        output.seek(0)
        return output.getvalue()

    except ImportError as exc:
        raise RuntimeError(
            "Për eksport Excel instalo openpyxl me: pip install openpyxl"
        ) from exc


def make_offer_text(
    project_name: str,
    h: float,
    w: float,
    d: float,
    element_type: str,
    costs: Dict[str, float],
) -> str:
    return (
        f"OFERTE - {project_name}\n"
        f"{'=' * 44}\n"
        f"Tipi: {element_type}\n"
        f"Dimensionet: H {h:.0f} x W {w:.0f} x D {d:.0f} mm\n\n"
        f"Siperfaqe neto: {costs['net_total_m2']:.3f} m2\n"
        f"Siperfaqe bruto: {costs['gross_total_m2']:.3f} m2\n"
        f"Kosto totale materiali: {costs['total_material_cost']:.2f} EUR\n"
        f"Fitimi / puna: {costs['profit_value']:.2f} EUR\n"
        f"CMIMI FINAL: {costs['final_price']:.2f} EUR\n"
    )


# ============================================================
# UI STYLING
# ============================================================
st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
        }
        div[data-testid="stMetric"] {
            background: rgba(127, 127, 127, 0.06);
            border: 1px solid rgba(127, 127, 127, 0.18);
            padding: 12px;
            border-radius: 12px;
        }
        .small-note {
            opacity: 0.78;
            font-size: 0.90rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HEADER
# ============================================================
st.title("🪚 WoodCut Pro")
st.caption(
    "Kalkulim profesional i prerjeve, kanteve, aksesorëve dhe ofertës për elemente kuzhine."
)


# ============================================================
# SIDEBAR INPUTS
# ============================================================
with st.sidebar:
    st.header("1. Masat bazë")

    project_name = st.text_input("Emri / Kodi i projektit", value="Element Kuzhine 001")

    h = st.number_input(
        "Lartësia H (mm)",
        min_value=0.0,
        max_value=4000.0,
        value=720.0,
        step=1.0,
    )
    w = st.number_input(
        "Gjerësia W (mm)",
        min_value=0.0,
        max_value=3000.0,
        value=600.0,
        step=1.0,
    )
    d = st.number_input(
        "Thellësia D (mm)",
        min_value=0.0,
        max_value=1500.0,
        value=560.0,
        step=1.0,
    )

    t = float(st.selectbox("Trashësia e pllakës", BOARD_THICKNESSES, index=1))
    abs_t = float(st.selectbox("Trashësia ABS", ABS_THICKNESSES, index=2))

    st.divider()
    st.header("2. Konfigurimi")

    element_type = st.radio(
        "Tipi i elementit",
        ["Element me Dyer", "Element me Sirtarë"],
    )

    door_count = 0
    shelf_count = 0
    drawer_count = 0

    if element_type == "Element me Dyer":
        door_count = st.selectbox("Numri i dyerve", [1, 2], index=0)
        shelf_count = st.number_input(
            "Numri i rafteve",
            min_value=0,
            max_value=10,
            value=1,
            step=1,
        )
    else:
        drawer_count = st.number_input(
            "Numri i sirtarëve",
            min_value=1,
            max_value=5,
            value=3,
            step=1,
        )
        shelf_count = st.number_input(
            "Rafte shtesë",
            min_value=0,
            max_value=5,
            value=0,
            step=1,
        )

    back_type = st.selectbox(
        "Prapavija",
        [
            "Lesonit 3mm me kanal (sofit)",
            "Lesonit 3mm i mbërthyer prapa",
        ],
    )

    with st.expander("Parametra teknikë"):
        door_gap = st.number_input(
            "Fuga e dyerve (mm)",
            min_value=2.0,
            max_value=6.0,
            value=DOOR_GAP_DEFAULT,
            step=0.5,
        )
        drawer_gap = st.number_input(
            "Fuga e fronteve të sirtarëve (mm)",
            min_value=2.0,
            max_value=6.0,
            value=DRAWER_FRONT_GAP_DEFAULT,
            step=0.5,
        )


# ============================================================
# FINANCIAL INPUTS
# ============================================================
st.subheader("Parametrat financiarë")

c1, c2, c3, c4 = st.columns(4)

with c1:
    board_price_m2 = st.number_input(
        "MDF / Ivericë €/m²",
        min_value=0.0,
        value=18.0,
        step=0.5,
    )
    hardboard_price_m2 = st.number_input(
        "Lesonit 3mm €/m²",
        min_value=0.0,
        value=5.0,
        step=0.5,
    )

with c2:
    hinge_price = st.number_input(
        "Bagllama €/copë",
        min_value=0.0,
        value=2.5,
        step=0.1,
    )
    handle_price = st.number_input(
        "Doreza €/copë",
        min_value=0.0,
        value=3.0,
        step=0.1,
    )

with c3:
    runner_set_price = st.number_input(
        "Shina €/set",
        min_value=0.0,
        value=10.0,
        step=0.5,
    )
    leg_price = st.number_input(
        "Këmbë €/copë",
        min_value=0.0,
        value=1.0,
        step=0.1,
    )

with c4:
    abs_price_m = st.number_input(
        "ABS €/m",
        min_value=0.0,
        value=0.55,
        step=0.05,
    )
    waste_percent = st.slider(
        "Skafi / mbetja (%)",
        min_value=0,
        max_value=30,
        value=15,
        step=1,
    )
    profit_percent = st.slider(
        "Margjina / puna (%)",
        min_value=0,
        max_value=150,
        value=50,
        step=5,
    )


# ============================================================
# CALCULATION + OUTPUT
# ============================================================
try:
    parts, hardware = build_cut_list(
        h=h,
        w=w,
        d=d,
        t=t,
        abs_t=abs_t,
        element_type=element_type,
        door_count=int(door_count),
        shelf_count=int(shelf_count),
        drawer_count=int(drawer_count),
        back_type=back_type,
        door_gap=float(door_gap),
        drawer_gap=float(drawer_gap),
    )

    costs = calculate_costs(
        parts=parts,
        hardware=hardware,
        board_price_m2=board_price_m2,
        hardboard_price_m2=hardboard_price_m2,
        hinge_price=hinge_price,
        handle_price=handle_price,
        runner_set_price=runner_set_price,
        leg_price=leg_price,
        abs_price_m=abs_price_m,
        waste_percent=waste_percent,
        profit_percent=profit_percent,
    )

    cut_df = cut_list_dataframe(parts)
    hw_df = hardware_dataframe(hardware)

    st.success("Kalkulimi u krye me sukses.")

    st.subheader("Lista e prerjeve")

    st.dataframe(
        cut_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sasia": st.column_config.NumberColumn(format="%d"),
            "Lartësia mm": st.column_config.NumberColumn(format="%.1f"),
            "Gjerësia mm": st.column_config.NumberColumn(format="%.1f"),
            "ABS m": st.column_config.NumberColumn(format="%.3f"),
            "Sipërfaqe m²": st.column_config.NumberColumn(format="%.4f"),
        },
    )

    st.subheader("Aksesorët")

    h1, h2, h3, h4, h5 = st.columns(5)

    h1.metric("Bagllama", f"{hardware.hinges} copë")
    h2.metric("Doreza", f"{hardware.handles} copë")
    h3.metric(
        "Shina",
        (
            f"{hardware.drawer_runner_sets} sete / {hardware.runner_length_mm} mm"
            if hardware.drawer_runner_sets
            else "0 sete"
        ),
    )
    h4.metric("Këmbë", f"{hardware.legs} copë")
    h5.metric("ABS total", f"{hardware.abs_m:.2f} m")

    st.dataframe(hw_df, use_container_width=True, hide_index=True)

    st.subheader("Përmbledhja financiare")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Sipërfaqja neto", f"{costs['net_total_m2']:.3f} m²")
    m2.metric("Sipërfaqja bruto", f"{costs['gross_total_m2']:.3f} m²")
    m3.metric("Kosto materiali", f"{costs['total_material_cost']:.2f} €")
    m4.metric("Oferta finale", f"{costs['final_price']:.2f} €")

    fc1, fc2, fc3 = st.columns(3)
    fc1.metric("Kosto MDF/Ivericë", f"{costs['board_cost']:.2f} €")
    fc2.metric("Kosto Lesonit", f"{costs['hardboard_cost']:.2f} €")
    fc3.metric("Kosto aksesorë + ABS", f"{costs['hardware_cost']:.2f} €")

    st.info(
        f"Fitimi / puna sipas marzhit të zgjedhur: "
        f"**{costs['profit_value']:.2f} €**"
    )

    st.subheader("Eksporto")

    csv_bytes = cut_df.to_csv(index=False).encode("utf-8-sig")
    offer_txt = make_offer_text(
        project_name=project_name,
        h=h,
        w=w,
        d=d,
        element_type=element_type,
        costs=costs,
    ).encode("utf-8")

    e1, e2, e3 = st.columns(3)

    with e1:
        st.download_button(
            "⬇️ Shkarko CSV",
            data=csv_bytes,
            file_name=f"{project_name.replace(' ', '_')}_cutlist.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with e2:
        try:
            excel_bytes = make_excel_bytes(
                cut_df=cut_df,
                hardware_df=hw_df,
                costs=costs,
                project_name=project_name,
            )

            st.download_button(
                "⬇️ Shkarko Excel",
                data=excel_bytes,
                file_name=f"{project_name.replace(' ', '_')}_oferta.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        except RuntimeError as excel_error:
            st.warning(str(excel_error))

    with e3:
        st.download_button(
            "⬇️ Shkarko Ofertën TXT",
            data=offer_txt,
            file_name=f"{project_name.replace(' ', '_')}_oferta.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.divider()

    st.markdown(
        """
        <div class="small-note">
        <b>Shënime teknike:</b><br>
        • ABS-i zbritet vetëm në dimensionet ku ka skaj të kantuar.<br>
        • Dyert/frontet trajtohen si overlay dhe kantohen në 4 anë.<br>
        • Për sirtarët përdoret 25 mm hapësirë totale për shinat standarde.<br>
        • Gjatësia e shinës zgjidhet automatikisht nga 400/450/500/550 mm sipas thellësisë.<br>
        • Skafi aplikohet vetëm mbi materialet në m², jo mbi aksesorët.<br>
        • Margjina/Puna aplikohet mbi koston totale të materialit dhe aksesorëve.
        </div>
        """,
        unsafe_allow_html=True,
    )

except ValueError as err:
    st.error(f"Gabim në parametra:\n\n{err}")

except Exception as err:
    st.error(
        "Ndodhi një gabim i papritur gjatë kalkulimit. "
        "Kontrollo parametrat ose varësitë e instalimit."
    )
    with st.expander("Detaje teknike"):
        st.code(str(err))
