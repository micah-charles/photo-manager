import CoreGraphics
import CoreML
import Foundation
import ImageIO
import Vision
import Darwin

private struct NormalizedBox: Encodable {
    let left: Double
    let top: Double
    let right: Double
    let bottom: Double
}

private struct FaceResult: Encodable {
    let box: NormalizedBox
    let confidence: Double
}

private struct SubjectResult: Encodable {
    let label: String
    let box: NormalizedBox
    let confidence: Double
}

private struct ImageResult: Encodable {
    let source: String
    let filename: String
    let width: Int
    let height: Int
    let exif_orientation: Int
    let coordinate_space: String
    let box_convention: String
    let elapsed_ms: Double
    let faces: [FaceResult]
    let subjects: [SubjectResult]
}

private struct ImageError: Encodable {
    let source: String
    let message: String
}

private struct BatchResult: Encodable {
    let schema_version: Int
    let engine: String
    let os_version: String
    let face_request_revision: Int
    let human_request_revision: Int
    let images: [ImageResult]
    let errors: [ImageError]
}

private enum AnalysisError: LocalizedError {
    case unreadableImage
    case missingDimensions

    var errorDescription: String? {
        switch self {
        case .unreadableImage: return "Vision could not open this image."
        case .missingDimensions: return "Image metadata did not include pixel dimensions."
        }
    }
}

private func normalizedTopLeftBox(_ rect: CGRect) -> NormalizedBox {
    // Vision uses a normalized bottom-left origin. The browser crop contract
    // uses normalized top-left coordinates in the EXIF-oriented image plane.
    let left = min(1, max(0, Double(rect.minX)))
    let right = min(1, max(0, Double(rect.maxX)))
    let top = min(1, max(0, 1 - Double(rect.maxY)))
    let bottom = min(1, max(0, 1 - Double(rect.minY)))
    return NormalizedBox(left: left, top: top, right: right, bottom: bottom)
}

private func analyze(_ sourcePath: String) throws -> ImageResult {
    let started = ContinuousClock.now
    let url = URL(fileURLWithPath: sourcePath).standardizedFileURL
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
    else { throw AnalysisError.unreadableImage }

    guard let rawWidth = (properties[kCGImagePropertyPixelWidth] as? NSNumber)?.intValue,
          let rawHeight = (properties[kCGImagePropertyPixelHeight] as? NSNumber)?.intValue,
          rawWidth > 0, rawHeight > 0
    else { throw AnalysisError.missingDimensions }

    let rawOrientation = (properties[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
    let orientation = (1...8).contains(rawOrientation) ? rawOrientation : 1
    let oriented = (5...8).contains(orientation)
    let width = oriented ? rawHeight : rawWidth
    let height = oriented ? rawWidth : rawHeight
    let imageOrientation = CGImagePropertyOrientation(rawValue: UInt32(orientation)) ?? .up
    let handler = VNImageRequestHandler(url: url, orientation: imageOrientation, options: [:])

    let faceRequest = VNDetectFaceRectanglesRequest()
    let humanRequest = VNDetectHumanRectanglesRequest()
    // Keep this initial POC predictable on Macs where Vision's default ANE
    // model asset is unavailable. Benchmark other compute devices before a
    // future background catalog worker chooses its execution policy.
    if #available(macOS 14.0, *), let cpu = MLComputeDevice.allComputeDevices.first(where: {
        if case .cpu = $0 { return true }
        return false
    }) {
        faceRequest.setComputeDevice(cpu, for: .main)
        humanRequest.setComputeDevice(cpu, for: .main)
    }
    humanRequest.upperBodyOnly = false
    try handler.perform([faceRequest, humanRequest])

    let faces = (faceRequest.results ?? []).map {
        FaceResult(box: normalizedTopLeftBox($0.boundingBox), confidence: Double($0.confidence))
    }.sorted {
        ($0.box.top, $0.box.left) < ($1.box.top, $1.box.left)
    }
    let subjects = (humanRequest.results ?? []).map {
        SubjectResult(label: "person", box: normalizedTopLeftBox($0.boundingBox), confidence: Double($0.confidence))
    }.sorted {
        ($0.box.top, $0.box.left) < ($1.box.top, $1.box.left)
    }

    let elapsed = started.duration(to: .now)
    let components = elapsed.components
    let elapsedMs = Double(components.seconds) * 1_000 + Double(components.attoseconds) / 1e15
    return ImageResult(
        source: url.path,
        filename: url.lastPathComponent,
        width: width,
        height: height,
        exif_orientation: orientation,
        coordinate_space: "oriented",
        box_convention: "normalized-top-left",
        elapsed_ms: elapsedMs,
        faces: faces,
        subjects: subjects
    )
}

let paths = Array(CommandLine.arguments.dropFirst())
guard !paths.isEmpty else {
    fputs("Usage: local_vision_analyzer.swift PHOTO [PHOTO ...]\n", stderr)
    exit(64)
}

private var images: [ImageResult] = []
private var errors: [ImageError] = []
for path in paths {
    do {
        let result = try analyze(path)
        images.append(result)
    } catch {
        errors.append(ImageError(source: URL(fileURLWithPath: path).standardizedFileURL.path, message: error.localizedDescription))
    }
}

// Request revisions are included as provenance, not as identity/model scores.
private let payload = BatchResult(
    schema_version: 1,
    engine: "apple-vision",
    os_version: ProcessInfo.processInfo.operatingSystemVersionString,
    face_request_revision: VNDetectFaceRectanglesRequest().revision,
    human_request_revision: VNDetectHumanRectanglesRequest().revision,
    images: images,
    errors: errors
)
do {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    FileHandle.standardOutput.write(try encoder.encode(payload))
    FileHandle.standardOutput.write(Data([0x0a]))
    if !errors.isEmpty { exit(1) }
} catch {
    fputs("Could not encode Vision results: \(error.localizedDescription)\n", stderr)
    exit(70)
}
