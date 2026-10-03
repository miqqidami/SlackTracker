#!/usr/bin/env python3
"""Render assets/AppIcon.icns: a macOS-style rounded square with a white SF Symbols stopwatch.

Run with the app's virtualenv (needs pyobjc-framework-Cocoa), on macOS 11+:
    python tools/make_icon.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSBitmapImageRep, NSGraphicsContext, NSColor, NSGradient, NSBezierPath, NSImage,
    NSImageSymbolConfiguration, NSShadow, NSMakeRect, NSPNGFileType, NSCompositingOperationSourceOver,
    NSCompositingOperationSourceAtop, NSRectFillUsingOperation,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "AppIcon.icns"
SIZE = 1024


def rgb(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r / 255, g / 255, b / 255, a)


def render_png(path: Path) -> None:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, SIZE, SIZE, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))

    # Apple's icon grid: 824pt body inside a 1024pt canvas, ~185pt corner radius.
    body = NSMakeRect(100, 100, 824, 824)
    shape = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(body, 185, 185)

    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(rgb(0, 0, 0, 0.35))
    shadow.setShadowOffset_((0, -12))
    shadow.setShadowBlurRadius_(28)
    NSGraphicsContext.saveGraphicsState()
    shadow.set()
    rgb(200, 48, 44).setFill()
    shape.fill()
    NSGraphicsContext.restoreGraphicsState()

    NSGradient.alloc().initWithStartingColor_endingColor_(rgb(255, 112, 94), rgb(196, 40, 40)) \
        .drawInBezierPath_angle_(shape, -90)

    # Soft top highlight for depth.
    NSGraphicsContext.saveGraphicsState()
    shape.addClip()
    highlight = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(-80, 560, 1184, 700))
    NSGradient.alloc().initWithStartingColor_endingColor_(rgb(255, 255, 255, 0.14), rgb(255, 255, 255, 0.0)) \
        .drawInBezierPath_angle_(highlight, -90)
    NSGraphicsContext.restoreGraphicsState()

    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(470, 0.3)
    symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("stopwatch", None) \
        .imageWithSymbolConfiguration_(config)
    # Tint the template symbol white.
    tinted = NSImage.alloc().initWithSize_(symbol.size())
    tinted.lockFocus()
    symbol.drawAtPoint_fromRect_operation_fraction_((0, 0), NSMakeRect(0, 0, 0, 0), NSCompositingOperationSourceOver, 1.0)
    NSColor.whiteColor().set()
    NSRectFillUsingOperation(NSMakeRect(0, 0, *symbol.size()), NSCompositingOperationSourceAtop)
    tinted.unlockFocus()

    w, h = tinted.size()
    glyph_shadow = NSShadow.alloc().init()
    glyph_shadow.setShadowColor_(rgb(90, 0, 0, 0.35))
    glyph_shadow.setShadowOffset_((0, -10))
    glyph_shadow.setShadowBlurRadius_(18)
    NSGraphicsContext.saveGraphicsState()
    glyph_shadow.set()
    tinted.drawInRect_(NSMakeRect((SIZE - w) / 2, (SIZE - h) / 2 - 8, w, h))
    NSGraphicsContext.restoreGraphicsState()

    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(str(path), True)


def main() -> None:
    work = Path(tempfile.mkdtemp())
    master = work / "icon_1024.png"
    render_png(master)
    iconset = work / "AppIcon.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(["sips", "-z", str(px), str(px), str(master), "--out", str(iconset / name)],
                           check=True, capture_output=True)
    OUT.parent.mkdir(exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(OUT)], check=True)
    shutil.copy(master, OUT.with_name("AppIcon.png"))
    shutil.rmtree(work)
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
