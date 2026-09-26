import AppKit
import CoreGraphics
import Foundation

func createIconBitmap(pixelSize: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: pixelSize,
        pixelsHigh: pixelSize,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    )!
    
    let size = CGFloat(pixelSize)
    let scale = size / 512.0
    
    NSGraphicsContext.saveGraphicsState()
    guard let context = NSGraphicsContext(bitmapImageRep: rep) else {
        NSGraphicsContext.restoreGraphicsState()
        return rep
    }
    NSGraphicsContext.current = context
    let cgContext = context.cgContext
    
    cgContext.clear(CGRect(x: 0, y: 0, width: size, height: size))
    
    // -------------------------------------------------------------------------
    // 1. macOS Squircle Base with Drop Shadow & Subtle Inner Highlight Border
    // -------------------------------------------------------------------------
    let shadowPadding = 45.0 * scale
    let squircleRect = CGRect(
        x: shadowPadding,
        y: shadowPadding,
        width: size - (shadowPadding * 2),
        height: size - (shadowPadding * 2)
    )
    let cornerRadius = 90.0 * scale
    
    // Drop Shadow
    cgContext.saveGState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.28)
    shadow.shadowOffset = NSSize(width: 0, height: -12.0 * scale)
    shadow.shadowBlurRadius = 18.0 * scale
    shadow.set()
    
    let squirclePath = NSBezierPath(roundedRect: squircleRect, xRadius: cornerRadius, yRadius: cornerRadius)
    
    // Vibrant Orange Gradient
    let colors = [
        NSColor(red: 1.0, green: 0.48, blue: 0.05, alpha: 1.0).cgColor,
        NSColor(red: 0.88, green: 0.28, blue: 0.02, alpha: 1.0).cgColor
    ]
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    if let gradient = CGGradient(colorsSpace: colorSpace, colors: colors as CFArray, locations: [0.0, 1.0]) {
        squirclePath.addClip()
        cgContext.drawLinearGradient(
            gradient,
            start: CGPoint(x: squircleRect.midX, y: squircleRect.maxY),
            end: CGPoint(x: squircleRect.midX, y: squircleRect.minY),
            options: []
        )
    }
    cgContext.restoreGState()
    
    // Subtle Inner Highlight Border
    cgContext.saveGState()
    let borderPath = NSBezierPath(roundedRect: squircleRect, xRadius: cornerRadius, yRadius: cornerRadius)
    borderPath.lineWidth = 2.0 * scale
    NSColor.white.withAlphaComponent(0.20).setStroke()
    borderPath.stroke()
    cgContext.restoreGState()
    
    // -------------------------------------------------------------------------
    // 2. Bold Clean Minimalist Football (Athletic, Balanced Curve, Zero Overshoot)
    // -------------------------------------------------------------------------
    cgContext.saveGState()
    
    // Ensure football stays strictly inside squircle
    let clipSquircle = NSBezierPath(roundedRect: squircleRect, xRadius: cornerRadius, yRadius: cornerRadius)
    clipSquircle.addClip()
    
    let cx = squircleRect.midX
    let cy = squircleRect.midY
    
    cgContext.translateBy(x: cx, y: cy)
    // Rotate ~42 degrees for athletic diagonal presentation
    cgContext.rotate(by: 42.0 * .pi / 180.0)
    
    cgContext.setLineCap(.round)
    cgContext.setLineJoin(.round)
    
    let strokeColor = NSColor.white.cgColor
    cgContext.setStrokeColor(strokeColor)
    
    let bodyLineWidth = 19.0 * scale
    let stripeLineWidth = 16.0 * scale
    let seamLineWidth = 13.0 * scale
    let laceLineWidth = 11.5 * scale
    
    // Proportions: Sleek authentic NFL football ratio (~1.56)
    let halfW: CGFloat = 128.0 * scale
    let halfH: CGFloat = 82.0 * scale
    let cxCtrl: CGFloat = 0.44
    let cyCtrl: CGFloat = 0.24
    
    // A. Balanced Football Body Path (Not needle-pointy, not overly round)
    // Smooth cubic Béziers with horizontal belly tangents and vertical tip tangents
    // create a refined, tapered silhouette with softly rounded tips (~7.5px radius).
    let body = CGMutablePath()
    body.move(to: CGPoint(x: 0, y: halfH))
    body.addCurve(to: CGPoint(x: halfW, y: 0),
                  control1: CGPoint(x: cxCtrl * halfW, y: halfH),
                  control2: CGPoint(x: halfW, y: cyCtrl * halfH))
    body.addCurve(to: CGPoint(x: 0, y: -halfH),
                  control1: CGPoint(x: halfW, y: -cyCtrl * halfH),
                  control2: CGPoint(x: cxCtrl * halfW, y: -halfH))
    body.addCurve(to: CGPoint(x: -halfW, y: 0),
                  control1: CGPoint(x: -cxCtrl * halfW, y: -halfH),
                  control2: CGPoint(x: -halfW, y: -cyCtrl * halfH))
    body.addCurve(to: CGPoint(x: 0, y: halfH),
                  control1: CGPoint(x: -halfW, y: cyCtrl * halfH),
                  control2: CGPoint(x: -cxCtrl * halfW, y: halfH))
    body.closeSubpath()
    
    // B. Left & Right Curved Stripes (Clipped to body so they NEVER overshoot)
    cgContext.saveGState()
    cgContext.addPath(body)
    cgContext.clip()
    
    let stripeX: CGFloat = 68.0 * scale
    let stripeH: CGFloat = halfH * 1.15
    
    // Left Stripe
    let leftStripe = CGMutablePath()
    leftStripe.move(to: CGPoint(x: -stripeX, y: stripeH))
    leftStripe.addQuadCurve(to: CGPoint(x: -stripeX, y: -stripeH),
                            control: CGPoint(x: -stripeX + 22.0 * scale, y: 0))
    cgContext.addPath(leftStripe)
    cgContext.setLineWidth(stripeLineWidth)
    cgContext.strokePath()
    
    // Right Stripe
    let rightStripe = CGMutablePath()
    rightStripe.move(to: CGPoint(x: stripeX, y: stripeH))
    rightStripe.addQuadCurve(to: CGPoint(x: stripeX, y: -stripeH),
                             control: CGPoint(x: stripeX - 22.0 * scale, y: 0))
    cgContext.addPath(rightStripe)
    cgContext.setLineWidth(stripeLineWidth)
    cgContext.strokePath()
    
    cgContext.restoreGState()
    
    // C. Stroke Football Outline on top
    // Merges seamlessly with the clipped stripes, guaranteeing zero line overshoot.
    cgContext.addPath(body)
    cgContext.setLineWidth(bodyLineWidth)
    cgContext.strokePath()
    
    // D. Center Seam Line (Subtly curved along upper contour)
    let seamY: CGFloat = 14.0 * scale
    let seamLen: CGFloat = 46.0 * scale
    let seam = CGMutablePath()
    seam.move(to: CGPoint(x: -seamLen, y: seamY + 3.0 * scale))
    seam.addQuadCurve(to: CGPoint(x: seamLen, y: seamY + 3.0 * scale),
                      control: CGPoint(x: 0, y: seamY + 11.0 * scale))
    cgContext.addPath(seam)
    cgContext.setLineWidth(seamLineWidth)
    cgContext.strokePath()
    
    // E. 5 Laces (Cross-Stitches along seam)
    let laceCount = 5
    let laceSpan: CGFloat = 32.0 * scale
    let laceHeight: CGFloat = 13.0 * scale
    let step = (laceSpan * 2) / CGFloat(laceCount - 1)
    
    for i in 0..<laceCount {
        let lx = -laceSpan + CGFloat(i) * step
        let normalized = (lx / seamLen)
        let ly = seamY + 7.0 * scale - (normalized * normalized * 4.0 * scale)
        
        let lace = CGMutablePath()
        lace.move(to: CGPoint(x: lx - 1.5 * scale, y: ly - laceHeight))
        lace.addLine(to: CGPoint(x: lx + 1.5 * scale, y: ly + laceHeight))
        cgContext.addPath(lace)
        cgContext.setLineWidth(laceLineWidth)
        cgContext.strokePath()
    }
    
    cgContext.restoreGState()
    NSGraphicsContext.restoreGraphicsState()
    
    return rep
}

func savePNG(rep: NSBitmapImageRep, path: String) -> Bool {
    guard let pngData = rep.representation(using: .png, properties: [:]) else {
        return false
    }
    do {
        try pngData.write(to: URL(fileURLWithPath: path))
        return true
    } catch {
        print("Failed to write to \(path): \(error)")
        return false
    }
}

// Generate all macOS icon sizes
let iconsetDir = "AppIcon.iconset"
let fileManager = FileManager.default

do {
    if fileManager.fileExists(atPath: iconsetDir) {
        try fileManager.removeItem(atPath: iconsetDir)
    }
    try fileManager.createDirectory(atPath: iconsetDir, withIntermediateDirectories: true, attributes: nil)
} catch {
    print("Failed to create \(iconsetDir) directory: \(error)")
    exit(1)
}

let sizes: [(String, Int)] = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024)
]

print("🎨 Generating Refined Minimalist NFL Fantasy HUD App Icon...")
for (name, pixelSize) in sizes {
    let rep = createIconBitmap(pixelSize: pixelSize)
    let path = "\(iconsetDir)/\(name)"
    if !savePNG(rep: rep, path: path) {
        print("Failed to save \(path)")
        exit(1)
    }
}

// Also save 512x512 for static web asset
let webRep = createIconBitmap(pixelSize: 512)
_ = savePNG(rep: webRep, path: "static/app_icon.png")

print("✅ App Icon PNGs successfully generated.")

// Automatically run iconutil to generate AppIcon.icns
let iconutilProcess = Process()
iconutilProcess.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutilProcess.arguments = ["-c", "icns", iconsetDir, "-o", "AppIcon.icns"]
do {
    try iconutilProcess.run()
    iconutilProcess.waitUntilExit()
    if iconutilProcess.terminationStatus == 0 {
        print("✅ Generated AppIcon.icns successfully.")
        
        // Copy to Mac app bundle if it exists
        let macAppResources = "NFL Fantasy HUD.app/Contents/Resources/AppIcon.icns"
        if fileManager.fileExists(atPath: "NFL Fantasy HUD.app/Contents/Resources") {
            try? fileManager.removeItem(atPath: macAppResources)
            try? fileManager.copyItem(atPath: "AppIcon.icns", toPath: macAppResources)
            print("✅ Copied AppIcon.icns to macOS App Bundle.")
        }
    } else {
        print("⚠️ iconutil exited with code \(iconutilProcess.terminationStatus)")
    }
} catch {
    print("⚠️ Failed to run iconutil: \(error)")
}
