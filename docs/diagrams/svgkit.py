"""Tiny SVG toolkit for hand-placed architecture diagrams.

Coordinates are explicit so connectors stay orthogonal and never cross.
Rendering to PNG uses `rsvg-convert` (librsvg) when it is installed.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"

INK = "#111827"
MUTED = "#475569"
FAINT = "#94a3b8"
ZONE_FILL = "#f8fafc"
ZONE_STROKE = "#cbd5e1"

PROPOSED = "#ea580c"
PROPOSED_FILL = "#fff7ed"
WARN = "#b91c1c"

# AWS service category colours.
ACCENT = {
    "storage": "#3f8624",
    "integration": "#e7157b",
    "database": "#3b48cc",
    "security": "#dd344c",
    "management": "#b0084d",
    "compute": "#ed7100",
    "network": "#8c4fff",
    "external": "#64748b",
    "people": "#334155",
}

PILLS = {
    "TERRAFORM": ("#1d4ed8", "#dbeafe"),
    "TF · OPTIONAL": ("#1d4ed8", "#dbeafe"),
    "CODE": ("#15803d", "#dcfce7"),
    "PROPOSED": ("#c2410c", "#ffedd5"),
    "ECS · PROPOSED": ("#c2410c", "#ffedd5"),
    "EXTERNAL": ("#334155", "#e2e8f0"),
    "RUNBOOK": ("#334155", "#e2e8f0"),
}


@dataclass(frozen=True)
class EdgeStyle:
    color: str
    width: float = 2.2
    dash: str | None = None


EDGES = {
    "data": EdgeStyle(INK),
    "proposed": EdgeStyle(PROPOSED),
    "retry": EdgeStyle("#d97706"),
    "dlq": EdgeStyle("#dc2626", 2.6),
    "redrive": EdgeStyle("#7c3aed", 2.6),
    "telemetry": EdgeStyle("#0d9488", 2.0, "2 5"),
    "iam": EdgeStyle("#6b7280", 1.8, "7 5"),
    "control": EdgeStyle("#334155", 1.8, "10 4 2 4"),
}


def _w(text: str, size: float, bold: bool = False) -> float:
    """Approximate rendered width for Helvetica."""
    return len(text) * size * (0.58 if bold else 0.52)


Line = str | tuple[str, dict[str, str]]


@dataclass
class Svg:
    width: int
    height: int
    zones: list[str] = field(default_factory=list)
    edges: list[str] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    # ---- primitives -----------------------------------------------------

    def text(
        self,
        x: float,
        y: float,
        s: str,
        *,
        size: float = 14,
        weight: str = "normal",
        color: str = INK,
        anchor: str = "start",
        halo: bool = False,
        italic: bool = False,
        layer: list[str] | None = None,
        spacing: float = 0,
    ) -> None:
        attrs = [
            f'x="{x:.1f}"',
            f'y="{y:.1f}"',
            f'font-size="{size}"',
            f'font-weight="{weight}"',
            f'fill="{color}"',
            f'text-anchor="{anchor}"',
            'xml:space="preserve"',
        ]
        if italic:
            attrs.append('font-style="italic"')
        if spacing:
            attrs.append(f'letter-spacing="{spacing}"')
        if halo:
            attrs.append(
                'stroke="#ffffff" stroke-width="5" stroke-linejoin="round" paint-order="stroke"'
            )
        (self.labels if layer is None else layer).append(
            f"<text {' '.join(attrs)}>{escape(s)}</text>"
        )

    def lines(
        self,
        x: float,
        y: float,
        items: Sequence[Line],
        *,
        size: float = 14,
        leading: float = 19,
        color: str = MUTED,
        anchor: str = "start",
        halo: bool = False,
        layer: list[str] | None = None,
    ) -> float:
        """Draw stacked lines; returns the baseline after the last line."""
        for item in items:
            text, opts = (item, {}) if isinstance(item, str) else item
            self.text(
                x,
                y,
                text,
                size=float(opts.get("size", size)),
                weight=opts.get("weight", "normal"),
                color=opts.get("color", color),
                anchor=anchor,
                halo=halo,
                italic=opts.get("italic") == "1",
                layer=layer,
            )
            y += leading
        return y

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        fill: str = "#ffffff",
        stroke: str = INK,
        width: float = 1.5,
        dash: str | None = None,
        rx: float = 8,
        layer: list[str] | None = None,
    ) -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        (self.nodes if layer is None else layer).append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{width}"{d}/>'
        )

    def pill(
        self,
        x: float,
        y: float,
        label: str,
        *,
        anchor: str = "end",
        fg: str | None = None,
        bg: str | None = None,
        size: float = 11.5,
        layer: list[str] | None = None,
    ) -> float:
        """Small rounded tag centred vertically on y. Returns its width."""
        pfg, pbg = PILLS.get(label, (INK, "#e5e7eb"))
        fg, bg = fg or pfg, bg or pbg
        w = _w(label, size, bold=True) + 16
        left = x - w if anchor == "end" else x
        target = self.labels if layer is None else layer
        target.append(
            f'<rect x="{left:.1f}" y="{y - 10:.1f}" width="{w:.1f}" height="20" rx="10" '
            f'fill="{bg}" stroke="{fg}" stroke-width="1"/>'
        )
        self.text(
            left + w / 2,
            y + 4,
            label,
            size=size,
            weight="bold",
            color=fg,
            anchor="middle",
            layer=target,
            spacing=0.4,
        )
        return w

    def badge(self, cx: float, cy: float, label: str, color: str = INK) -> None:
        self.labels.append(
            f'<circle cx="{cx}" cy="{cy}" r="11" fill="{color}" stroke="#ffffff" stroke-width="2"/>'
        )
        self.text(
            cx,
            cy + 4.5,
            label,
            size=13,
            weight="bold",
            color="#ffffff",
            anchor="middle",
        )

    # ---- composites -----------------------------------------------------

    def zone(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        *,
        proposed: bool = False,
    ) -> None:
        if proposed:
            self.rect(
                x,
                y,
                w,
                h,
                fill=PROPOSED_FILL,
                stroke=PROPOSED,
                width=2,
                dash="9 6",
                rx=12,
                layer=self.zones,
            )
        else:
            self.rect(
                x,
                y,
                w,
                h,
                fill=ZONE_FILL,
                stroke=ZONE_STROKE,
                width=1.5,
                rx=12,
                layer=self.zones,
            )
        self.text(
            x + 16,
            y + 24,
            title,
            size=14,
            weight="bold",
            color=PROPOSED if proposed else MUTED,
            spacing=0.8,
            layer=self.zones,
        )

    def node(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        title: str,
        body: Sequence[Line] = (),
        *,
        accent: str = "external",
        status: Sequence[str] = (),
        proposed: bool = False,
        chips: Sequence[str] = (),
        title_size: float = 17,
        body_size: float = 14,
        leading: float = 19,
    ) -> None:
        colour = ACCENT.get(accent, accent)
        if proposed:
            self.rect(
                x, y, w, h, fill=PROPOSED_FILL, stroke=PROPOSED, width=2, dash="8 5"
            )
        else:
            self.rect(x, y, w, h, fill="#ffffff", stroke=colour, width=1.8)
            self.nodes.append(
                f'<path d="M{x + 1},{y + 8} a7,7 0 0 1 7,-7 h{w - 16} a7,7 0 0 1 7,7 v2 h{-(w - 2)} z" '
                f'fill="{colour}"/>'
            )
        self.text(
            x + 14, y + 34, title, size=title_size, weight="bold", layer=self.nodes
        )
        self.lines(
            x + 14, y + 56, body, size=body_size, leading=leading, layer=self.nodes
        )
        px = x + w - 10
        for label in status:
            px -= self.pill(px, y, label, layer=self.nodes) + 6
        cx = x + 14
        for chip in chips:
            fg, bg = (
                ("#7c2d12", "#fef3c7") if chip.startswith("KMS") else (MUTED, "#f1f5f9")
            )
            cx += (
                self.pill(
                    cx,
                    y + h - 16,
                    chip,
                    anchor="start",
                    fg=fg,
                    bg=bg,
                    size=11,
                    layer=self.nodes,
                )
                + 6
            )

    def edge(
        self,
        points: Sequence[tuple[float, float]],
        kind: str = "data",
        *,
        head: bool = True,
    ) -> None:
        style = EDGES[kind]
        d = " ".join(
            f"{'M' if i == 0 else 'L'}{px},{py}" for i, (px, py) in enumerate(points)
        )
        dash = f' stroke-dasharray="{style.dash}"' if style.dash else ""
        marker = f' marker-end="url(#arrow-{kind})"' if head else ""
        self.edges.append(
            f'<path d="{d}" fill="none" stroke="{style.color}" stroke-width="{style.width}" '
            f'stroke-linejoin="round"{dash}{marker}/>'
        )

    def label(
        self,
        x: float,
        y: float,
        text: str,
        *,
        badge: str | None = None,
        color: str = INK,
        size: float = 14,
        weight: str = "bold",
        anchor: str = "start",
        badge_color: str | None = None,
    ) -> None:
        if badge:
            self.badge(x + 11, y - 5, badge, badge_color or color)
            x += 28
        self.text(
            x, y, text, size=size, weight=weight, color=color, anchor=anchor, halo=True
        )

    # ---- output ---------------------------------------------------------

    def _defs(self) -> str:
        markers = []
        for kind, style in EDGES.items():
            markers.append(
                f'<marker id="arrow-{kind}" viewBox="0 0 12 12" refX="11" refY="6" '
                f'markerWidth="12" markerHeight="12" markerUnits="userSpaceOnUse" orient="auto">'
                f'<path d="M0,1 L12,6 L0,11 z" fill="{style.color}"/></marker>'
            )
        return "<defs>" + "".join(markers) + "</defs>"

    def render(self) -> str:
        body = "\n".join(
            [
                f'<rect width="{self.width}" height="{self.height}" fill="#ffffff"/>',
                *self.zones,
                *self.edges,
                *self.nodes,
                *self.labels,
            ]
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
            f'font-family="{FONT}">\n{self._defs()}\n{body}\n</svg>\n'
        )

    def save(self, svg_path: Path, png_path: Path | None = None) -> None:
        svg_path.write_text(self.render(), encoding="utf-8")
        print(f"wrote {svg_path}")
        if png_path is None:
            return
        rsvg = shutil.which("rsvg-convert")
        if rsvg is None:
            print("rsvg-convert not found (brew install librsvg); PNG not refreshed")
            return
        subprocess.run(
            [rsvg, "--background-color", "white", "-o", str(png_path), str(svg_path)],
            check=True,
        )
        print(f"wrote {png_path}")


def legend_swatch(
    svg: Svg, x: float, y: float, kind: str, text: str, length: float = 46
) -> float:
    svg.edge([(x, y), (x + length, y)], kind)
    svg.text(x + length + 10, y + 5, text, size=14, color=INK)
    return x + length + 10 + _w(text, 14) + 34
