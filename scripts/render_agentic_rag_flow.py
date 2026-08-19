from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "diagrams" / "agentic_rag_flow_cn.png"
FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")

WIDTH = 1800
HEIGHT = 2300

COLORS = {
    "ink": "#17202A",
    "muted": "#566573",
    "line": "#7B8794",
    "blue": "#DCEEFF",
    "blue_border": "#2F6FA3",
    "green": "#DFF4E5",
    "green_border": "#2F7D4A",
    "amber": "#FFF0CC",
    "amber_border": "#A96B00",
    "red": "#FBE2E2",
    "red_border": "#A83A3A",
    "violet": "#ECE7FA",
    "violet_border": "#6650A4",
    "gray": "#F3F5F7",
    "gray_border": "#69747C",
    "white": "#FFFFFF",
}


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidate = Path("C:/Windows/Fonts/msyhbd.ttc") if bold else FONT_PATH
    return ImageFont.truetype(str(candidate), size)


image = Image.new("RGB", (WIDTH, HEIGHT), COLORS["white"])
draw = ImageDraw.Draw(image)


def centered_text(box: tuple[int, int, int, int], text: str, size: int, *, bold: bool = False, color: str | None = None) -> None:
    active_font = font(size, bold=bold)
    lines = text.split("\n")
    spacing = 12
    bounds = [draw.textbbox((0, 0), line, font=active_font) for line in lines]
    heights = [bound[3] - bound[1] for bound in bounds]
    total_height = sum(heights) + spacing * (len(lines) - 1)
    y = box[1] + (box[3] - box[1] - total_height) / 2
    for line, bound, line_height in zip(lines, bounds, heights):
        line_width = bound[2] - bound[0]
        x = box[0] + (box[2] - box[0] - line_width) / 2
        draw.text((x, y), line, font=active_font, fill=color or COLORS["ink"])
        y += line_height + spacing


def box(x: int, y: int, w: int, h: int, text: str, fill: str, border: str, *, size: int = 34) -> tuple[int, int, int, int]:
    bounds = (x, y, x + w, y + h)
    draw.rounded_rectangle(bounds, radius=18, fill=fill, outline=border, width=4)
    centered_text(bounds, text, size, bold=True)
    return bounds


def arrow(start: tuple[int, int], end: tuple[int, int], *, color: str | None = None, width: int = 6) -> None:
    active_color = color or COLORS["line"]
    draw.line((start, end), fill=active_color, width=width)
    x2, y2 = end
    x1, y1 = start
    if abs(x2 - x1) > abs(y2 - y1):
        sign = 1 if x2 > x1 else -1
        points = [(x2, y2), (x2 - 18 * sign, y2 - 12), (x2 - 18 * sign, y2 + 12)]
    else:
        sign = 1 if y2 > y1 else -1
        points = [(x2, y2), (x2 - 12, y2 - 18 * sign), (x2 + 12, y2 - 18 * sign)]
    draw.polygon(points, fill=active_color)


def label(x: int, y: int, text: str, *, color: str | None = None) -> None:
    draw.text((x, y), text, font=font(27, bold=True), fill=color or COLORS["muted"])


draw.text((110, 70), "Enterprise Agentic RAG Copilot", font=font(60, bold=True), fill=COLORS["ink"])
draw.text((110, 150), "受控决策循环、证据账本与安全边界", font=font(36), fill=COLORS["muted"])

# Intake and analysis.
user = box(590, 245, 620, 105, "用户问题 + 可信身份", COLORS["blue"], COLORS["blue_border"])
analysis = box(500, 415, 800, 125, "Query Analysis\n意图 / 实体 / 时间 / 风险", COLORS["blue"], COLORS["blue_border"])
arrow((900, user[3]), (900, analysis[1]))

unsafe = box(120, 615, 500, 115, "危险请求\n零工具调用，直接拒绝", COLORS["red"], COLORS["red_border"], size=31)
aspects = box(730, 615, 720, 115, "生成 required_aspects\n回答必须覆盖的证据目标", COLORS["green"], COLORS["green_border"], size=31)
arrow((650, analysis[3]), (440, unsafe[1]))
arrow((1080, analysis[3]), (1090, aspects[1]))
label(475, 560, "是", color=COLORS["red_border"])
label(1115, 560, "否", color=COLORS["green_border"])

# Main Agent loop.
controller = box(680, 805, 440, 115, "Controller\n决定下一步动作", COLORS["violet"], COLORS["violet_border"])
arrow((1090, aspects[3]), (900, controller[1]))

search = box(120, 1000, 400, 110, "SEARCH\n混合检索候选", COLORS["amber"], COLORS["amber_border"], size=31)
find = box(700, 1000, 400, 110, "FIND\n授权内容内查找", COLORS["amber"], COLORS["amber_border"], size=31)
open_box = box(1280, 1000, 400, 110, "OPEN\n按索引 ID 打开", COLORS["amber"], COLORS["amber_border"], size=31)
arrow((760, controller[3]), (320, search[1]))
arrow((900, controller[3]), (900, find[1]))
arrow((1040, controller[3]), (1480, open_box[1]))

guard = box(430, 1190, 940, 125, "宿主安全边界\nACL 权限检查 + Retrieved-content Injection Guard", COLORS["red"], COLORS["red_border"], size=31)
arrow((320, search[3]), (650, guard[1]))
arrow((900, find[3]), (900, guard[1]))
arrow((1480, open_box[3]), (1150, guard[1]))

observation = box(580, 1395, 640, 110, "Observation\n只接收已授权、已过滤证据", COLORS["green"], COLORS["green_border"], size=31)
arrow((900, guard[3]), (900, observation[1]))

ledger = box(520, 1580, 760, 135, "Evidence Ledger\nsupported / missing / conflicts / coverage", COLORS["violet"], COLORS["violet_border"], size=31)
arrow((900, observation[3]), (900, ledger[1]))

# Loop line from ledger back to controller.
draw.line((520, 1647, 260, 1647, 260, 862, 680, 862), fill=COLORS["violet_border"], width=6)
arrow((260, 862), (680, 862), color=COLORS["violet_border"])
label(285, 1515, "证据不足且预算允许：继续循环", color=COLORS["violet_border"])

# Terminal generation and verification.
generation = box(1300, 1580, 390, 135, "证据满足\nLLM 生成 Claims", COLORS["blue"], COLORS["blue_border"], size=31)
arrow((1280, 1647), (1300, 1647))

verify = box(1230, 1800, 530, 120, "Citation Verifier\n逐 Claim 校验证据", COLORS["green"], COLORS["green_border"], size=31)
arrow((1495, generation[3]), (1495, verify[1]))

terminal = box(1030, 2000, 730, 125, "结构化结果\n完整回答 / 部分回答 / 拒绝 / 停止 + Trace", COLORS["gray"], COLORS["gray_border"], size=30)
arrow((1495, verify[3]), (1495, terminal[1]))

other_terminal = box(90, 1835, 760, 155, "其他终止条件\n无证据 / 无权限 / 内容被隔离 / 超预算 / 系统错误", COLORS["gray"], COLORS["gray_border"], size=29)
arrow((520, ledger[3]), (470, other_terminal[1]))

# Footer note.
draw.rounded_rectangle((90, 2180, 1710, 2260), radius=14, fill="#FFF8E8", outline=COLORS["amber_border"], width=3)
centered_text(
    (110, 2185, 1690, 2255),
    "真实边界：这是 bounded Agent。当前外部评测中多数请求仍退化为一次 SEARCH，FIND/OPEN 的质量收益尚未得到证明。",
    27,
    color=COLORS["ink"],
)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUTPUT, format="PNG", optimize=True, dpi=(180, 180))
print(OUTPUT)
